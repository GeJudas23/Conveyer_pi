import base64
import logging
import time

import serial

from config import SERIAL_PORT, SERIAL_BAUD, _CMD_MAP, _REST_MAP

logger = logging.getLogger(__name__)

_RECONNECT_DELAY = 5  # секунд между попытками переподключения


class SerialManager:
    def __init__(self, camera, classifier, state, socketio):
        self._camera = camera
        self._classifier = classifier
        self._state = state
        self._socketio = socketio
        self._serial: serial.Serial | None = None
        self._running = False

    # ──────────────────────────────────────────────
    # Подключение
    # ──────────────────────────────────────────────

    def _connect(self) -> bool:
        """Попытаться открыть Serial-порт. Возвращает True при успехе."""
        try:
            self._serial = serial.Serial(
                SERIAL_PORT,
                SERIAL_BAUD,
                timeout=30,
            )
            self._state.status["arduino"] = True
            self._emit_status()
            logger.info("Serial connected: %s @ %d baud", SERIAL_PORT, SERIAL_BAUD)
            return True
        except serial.SerialException as e:
            self._serial = None
            self._state.status["arduino"] = False
            self._emit_status()
            logger.error("Serial connect failed (%s): %s", SERIAL_PORT, e)
            return False

    def _is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    # ──────────────────────────────────────────────
    # Отправка команд
    # ──────────────────────────────────────────────

    def _send_raw(self, cmd: str) -> None:
        """Отправить строку в Arduino (добавляет \n)."""
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
        """Отправить команду сброса по результату классификации."""
        cmd = _CMD_MAP.get(class_name, "3")  # неизвестный класс → конец ленты
        self._send_raw(cmd)
        logger.info("DROP %s → Arduino cmd '%s'", class_name, cmd)

    def send_manual_cmd(self, cmd: str) -> None:
        """REST /api/cmd: принимает 'DROP_A'/'DROP_B'/'DROP_C'/'DROP_REJ'/'STOP'."""
        raw = _REST_MAP.get(cmd.upper())
        if raw is None:
            logger.warning("Unknown manual cmd: %s", cmd)
            return
        self._send_raw(raw)
        logger.info("Manual cmd: %s → '%s'", cmd, raw)

    # ──────────────────────────────────────────────
    # SocketIO helpers
    # ──────────────────────────────────────────────

    def _emit_status(self) -> None:
        try:
            self._socketio.emit("status", self._state.status)
        except Exception as e:
            logger.debug("socketio emit status error: %s", e)

    # ──────────────────────────────────────────────
    # Основной цикл
    # ──────────────────────────────────────────────

    def run_loop(self) -> None:
        """
        Блокирующий главный цикл. Читает строки от Arduino и реагирует:

          "READY: ..."   → захват → классификация → отправить команду → emit
          "Ready for next..." → лог (цикл завершён)
          "ERROR..."     → лог ошибки

        Serial.timeout=30 с — при истечении readline() вернёт b'',
        цикл логирует предупреждение и продолжает (не падает).
        """
        self._running = True
        logger.info("Serial run_loop started")

        while self._running:
            # ── Переподключение ──────────────────
            if not self._is_open():
                if not self._connect():
                    time.sleep(_RECONNECT_DELAY)
                    continue

            # ── Чтение строки ────────────────────
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
                # readline() вернул пустую строку — таймаут 30 с
                logger.warning("Serial timeout (30 s) — no data from Arduino")
                continue

            logger.debug("← Arduino: %s", line)

            # ── Разбор строки ────────────────────
            try:
                if "READY:" in line:
                    self._handle_ready()
                elif "Ready for next" in line:
                    logger.info("Arduino: cycle complete")
                elif "ERROR" in line.upper():
                    logger.error("Arduino error: %s", line)
                    self._state.status["arduino"] = False
                    self._emit_status()
                else:
                    logger.debug("Arduino unhandled: %s", line)

            except KeyboardInterrupt:
                break
            except Exception:
                logger.exception("Exception in run_loop handler (continuing)")

    def _handle_ready(self) -> None:
        """Обработчик EVT:READY — захват, классификация, отправка, emit."""
        t0 = time.time()

        # 1. Захват кадра
        try:
            frame = self._camera.capture()
            self._state.status["camera"] = True
        except Exception as e:
            logger.error("Camera capture failed: %s", e)
            self._state.status["camera"] = False
            self._emit_status()
            self._send_drop("reject")
            return

        # 2. Классификация
        try:
            class_name, confidence, inference_ms = self._classifier.run(frame)
            self._state.status["nn"] = True
        except Exception as e:
            logger.error("Classifier error: %s — sending DROP_REJ", e)
            self._state.status["nn"] = False
            self._emit_status()
            self._send_drop("reject")
            return

        cycle_ms = (time.time() - t0) * 1000

        result = {
            "class_name":   class_name,
            "confidence":   round(confidence, 4),
            "cycle_ms":     round(cycle_ms, 1),
            "inference_ms": round(inference_ms, 1),
            "timestamp":    time.time(),
        }

        # 3. Обновить состояние
        self._state.update(result)

        # 4. Отправить команду Arduino
        self._send_drop(class_name)

        # 5. Подготовить JPEG и отправить в браузер
        try:
            jpeg_bytes = self._camera.frame_to_jpeg(frame)
            image_b64 = base64.b64encode(jpeg_bytes).decode()
        except Exception as e:
            logger.warning("JPEG encode failed: %s", e)
            image_b64 = ""

        snapshot = self._state.get_snapshot()
        emit_data = {
            **result,
            "image_b64":    image_b64,
            "counts":       snapshot["counts"],
            "total":        snapshot["total"],
            "avg_cycle_ms": snapshot["avg_cycle_ms"],
        }
        try:
            self._socketio.emit("new_result", emit_data)
        except Exception as e:
            logger.warning("SocketIO emit error: %s", e)

        logger.info(
            "Cycle done: class=%s conf=%.2f cycle=%.0f ms",
            class_name, confidence, cycle_ms,
        )

    # ──────────────────────────────────────────────
    # Завершение работы
    # ──────────────────────────────────────────────

    def close(self) -> None:
        self._running = False
        if self._is_open():
            try:
                self._serial.close()
                logger.info("Serial port closed")
            except Exception as e:
                logger.warning("Serial close error: %s", e)
