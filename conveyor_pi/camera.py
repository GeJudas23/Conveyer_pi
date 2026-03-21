import io
import logging
import numpy as np
from PIL import Image
from picamera2 import Picamera2

from config import IMG_SIZE, FRAME_WARMUP

logger = logging.getLogger(__name__)


class Camera:
    def __init__(self):
        logger.info("Initializing Pi Camera 3 (picamera2)...")
        self._cam = Picamera2()
        cfg = self._cam.create_still_configuration(
            main={"size": (1920, 1080), "format": "RGB888"},
        )
        self._cam.configure(cfg)
        self._cam.start()
        logger.info("Camera started, warming up (%d frames)...", FRAME_WARMUP)
        for _ in range(FRAME_WARMUP):
            self._cam.capture_array()
        logger.info("Camera ready")

    def capture(self) -> np.ndarray:
        """Захватить кадр. Возвращает RGB numpy array (H×W×3, uint8)."""
        frame = self._cam.capture_array()
        return frame

    def frame_to_jpeg(self, frame: np.ndarray, quality: int = 85) -> bytes:
        """Конвертировать RGB numpy array в JPEG bytes."""
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
