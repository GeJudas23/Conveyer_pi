import base64
import logging
import threading
import time

import serial

from config import _CMD_MAP, _REST_MAP, SERIAL_BAUD, SERIAL_PORT

logger = logging.getLogger(__name__)

_RECONNECT_DELAY = 5


class SerialManager:
    def __init__(self, camera, classifier, state, socketio, ser=None):
        self._camera = camera
        self._classifier = classifier
        self._state = state
        self._socketio = socketio
        self._serial = ser  # используем уже открытый порт
        self._running = False

    def _connect(self) -> bool:
        if self._serial and self._serial.is_open:
            self._state.status["arduino"] = True
            # Не emit здесь — статус обновится при следующем on_connect
            logger.info("Using existing serial port: %s", self._serial.port)
            return True
        try:
            self._serial = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
            self._state.status["arduino"] = True
            logger.info("Serial connected: %s @ %d baud", SERIAL_PORT, SERIAL_BAUD)
            return True
        except serial.SerialException as e:
            self._serial = None
            self._state.status["arduino"] = False
            logger.error("Serial connect failed (%s): %s", SERIAL_PORT, e)
            return False

    def _is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _send_raw(self, cmd: str) -> None:
        if not self._is_open():
            logger.warning("Cannot send '%s': port not open", cmd)
            return
        try:
            self._serial.write(f"{cmd}\n".encode())
            self._serial.flush()
            logger.debug("→ Arduino: %s", cmd)
        except serial.SerialException as e:
            logger.error("Serial write error: %s", e)
            self._state.status["arduino"] = False
            self._emit_status()

    def _send_drop(self, class_name: str) -> None:
        cmd = _CMD_MAP.get(class_name, "3")
        self._send_raw(cmd)
        logger.info("DROP %s → Arduino cmd '%s'", class_name, cmd)

    def send_manual_cmd(self, cmd: str) -> None:
        allowed = {"START", "STOP"}
        if cmd.upper() not in allowed:
            logger.warning("Unknown manual cmd: %s", cmd)
            return
        self._send_raw(cmd.upper())
        logger.info("Manual cmd: %s", cmd)

    def _emit_status(self) -> None:
        try:
            self._socketio.emit("status", self._state.status)
        except Exception as e:
            logger.debug("socketio emit status error: %s", e)

    def run_loop(self) -> None:
        """Запускает Serial-цикл в настоящем OS-потоке, минуя eventlet."""
        self._running = True
        t = threading.Thread(target=self._serial_thread, daemon=False)
        t.start()
        t.join()

    def _serial_thread(self) -> None:
        logger.info("Serial thread started (native OS thread)")
        last_status_emit = 0

        while self._running:
            if not self._is_open():
                if not self._connect():
                    time.sleep(_RECONNECT_DELAY)
                    continue

            # Периодически шлём статус (каждые 3 секунды)
            now = time.time()
            if now - last_status_emit > 3:
                self._emit_status()
                last_status_emit = now

            try:
                raw = self._serial.readline()
            except serial.SerialException as e:
                logger.error("Serial read error: %s", e)
                self._state.status["arduino"] = False
                self._emit_status()
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
                time.sleep(_RECONNECT_DELAY)
                continue

            line = raw.decode(errors="replace").strip()

            if not line:
                continue

            logger.debug("← Arduino: %s", line)

            try:
                if "READY:" in line:
                    logger.info("Arduino READY — capturing...")
                    self._handle_ready()
                elif "Ready for next" in line:
                    logger.info("Arduino: cycle complete")
                elif "ERROR" in line.upper():
                    logger.error("Arduino error: %s", line)
                    self._state.status["arduino"] = False
                    self._emit_status()
                else:
                    logger.debug("Arduino: %s", line)
            except Exception:
                logger.exception("Exception in serial handler (continuing)")

    def _light_on(self) -> None:
        self._send_raw("LON")
        logger.debug("Light ON")

    def _light_off(self) -> None:
        self._send_raw("LOFF")
        logger.debug("Light OFF")

    def _handle_ready(self) -> None:
        t0 = time.time()

        # Включаем свет
        self._light_on()
        time.sleep(0.3)  # даём свету стабилизироваться

        try:
            frame = self._camera.capture()
            self._state.status["camera"] = True
        except Exception as e:
            logger.error("Camera capture failed: %s", e)
            self._state.status["camera"] = False
            self._emit_status()
            self._light_off()
            self._send_drop("empty")
            return

        # Выключаем свет сразу после захвата
        self._light_off()

        try:
            class_name, confidence, inference_ms = self._classifier.run(frame)
            self._state.status["nn"] = True
        except Exception as e:
            logger.error("Classifier error: %s", e)
            self._state.status["nn"] = False
            self._emit_status()
            self._send_drop("empty")
            return

        cycle_ms = (time.time() - t0) * 1000

        result = {
            "class_name": class_name,
            "confidence": round(confidence, 4),
            "cycle_ms": round(cycle_ms, 1),
            "inference_ms": round(inference_ms, 1),
            "timestamp": time.time(),
        }

        try:
            jpeg_bytes = self._camera.frame_to_jpeg(frame)
            result["image_b64"] = base64.b64encode(jpeg_bytes).decode()
        except Exception as e:
            logger.warning("JPEG encode failed: %s", e)
            result["image_b64"] = ""

        self._state.update(result)
        self._send_drop(class_name)

        snapshot = self._state.get_snapshot()
        emit_data = {
            **result,
            "counts": snapshot["counts"],
            "total": snapshot["total"],
            "avg_cycle_ms": snapshot["avg_cycle_ms"],
        }
        try:
            self._socketio.emit("new_result", emit_data)
        except Exception as e:
            logger.warning("SocketIO emit error: %s", e)

        logger.info(
            "Cycle done: class=%s conf=%.2f cycle=%.0f ms",
            class_name,
            confidence,
            cycle_ms,
        )

    def close(self) -> None:
        self._running = False
        if self._is_open():
            try:
                self._serial.close()
                logger.info("Serial port closed")
            except Exception as e:
                logger.warning("Serial close error: %s", e)
