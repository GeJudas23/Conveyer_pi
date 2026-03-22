import io
import logging
import time

import numpy as np
from libcamera import controls
from picamera2 import Picamera2
from PIL import Image

from config import FRAME_WARMUP

logger = logging.getLogger(__name__)


class Camera:
    def __init__(self, serial_port=None):
        self._serial = serial_port

        logger.info("Initializing Pi Camera 3 (picamera2)...")
        self._cam = Picamera2()
        cfg = self._cam.create_still_configuration(
            main={"size": (1920, 1080), "format": "RGB888"},
        )
        self._cam.configure(cfg)
        self._cam.start()

        # Включаем свет для калибровки
        self._send_light("LON")

        # Автофокус
        self._cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})

        # Ждём стабилизации AE под рабочим светом на пустой ленте
        logger.info("Waiting for AE to stabilise...")
        prev_exp = None
        stable_count = 0
        deadline = time.time() + 10
        while time.time() < deadline:
            self._cam.capture_array()
            meta = self._cam.capture_metadata()
            exp = meta.get("ExposureTime", 0)
            if prev_exp is not None:
                delta = abs(exp - prev_exp) / max(prev_exp, 1)
                if delta < 0.05:
                    stable_count += 1
                    if stable_count >= 5:
                        logger.info("AE stable at ExposureTime=%d", exp)
                        break
                else:
                    stable_count = 0
            prev_exp = exp

        # Прогрев
        logger.info("Warming up (%d frames)...", FRAME_WARMUP)
        for _ in range(FRAME_WARMUP):
            self._cam.capture_array()

        # Фиксируем экспозицию и баланс белого
        meta = self._cam.capture_metadata()
        exposure = meta.get("ExposureTime")
        gain = meta.get("AnalogueGain")
        awb_gains = meta.get("ColourGains")

        logger.info(
            "Locking: ExposureTime=%s AnalogueGain=%.2f ColourGains=%s",
            exposure,
            gain or 0,
            awb_gains,
        )

        lock = {
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": exposure,
            "AnalogueGain": gain,
        }
        if awb_gains:
            lock["ColourGains"] = awb_gains

        self._cam.set_controls(lock)
        time.sleep(0.5)

        # Выключаем свет — SerialManager будет включать при каждом кадре
        self._send_light("LOFF")

        logger.info("Camera ready (exposure locked)")

    def _send_light(self, cmd: str) -> None:
        """Отправить LIGHT_ON / LIGHT_OFF напрямую через Serial."""
        if self._serial and self._serial.is_open:
            try:
                self._serial.write(f"{cmd}\n".encode())
                self._serial.flush()
                logger.info("%s sent", cmd)
            except Exception as e:
                logger.warning("%s failed: %s", cmd, e)
        else:
            logger.warning("%s skipped — serial is None or closed", cmd)

    def capture(self) -> np.ndarray:
        frame = self._cam.capture_array()
        return frame[:, :, ::-1].copy()  # BGR → RGB

    def frame_to_jpeg(self, frame: np.ndarray, quality: int = 85) -> bytes:
        img = Image.fromarray(frame)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def close(self):
        try:
            self._cam.stop()
            self._cam.close()
            logger.info("Camera closed")
        except Exception as e:
            logger.warning("Camera close error: %s", e)
