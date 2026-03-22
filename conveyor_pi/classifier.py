import logging
import time

import numpy as np
from PIL import Image

from config import CLASS_NAMES, CONFIDENCE_MIN, MODEL_PATH

logger = logging.getLogger(__name__)


class Classifier:
    def __init__(self):
        import onnxruntime as ort

        logger.info("Loading ONNX model: %s", MODEL_PATH)
        self._session = ort.InferenceSession(
            MODEL_PATH,
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name
        inp = self._session.get_inputs()[0]
        logger.info("Model input: %s shape=%s dtype=%s", inp.name, inp.shape, inp.type)
        logger.info("Model classes: %s", CLASS_NAMES)

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]

        # Crop центра — без ограничения 1080
        side = min(h, w)
        y0 = (h - side) // 2
        x0 = (w - side) // 2
        cropped = frame[y0 : y0 + side, x0 : x0 + side]

        # frame уже RGB (мы делаем BGR→RGB в camera.py)
        # поэтому здесь НЕ переворачиваем каналы
        img = Image.fromarray(cropped).resize((224, 224), Image.BILINEAR)

        # Только /255 — без ImageNet нормализации
        arr = np.array(img, dtype=np.float32) / 255.0

        # HWC → NCHW
        arr = arr.transpose(2, 0, 1)[np.newaxis]
        return arr

    def run(self, frame: np.ndarray) -> tuple[str, float, float]:
        t0 = time.time()
        x = self._preprocess(frame)
        outputs = self._session.run(None, {self._input_name: x})
        logits = outputs[0][0]

        # Логиты уже в [0,1] — возможно внутри модели уже softmax/sigmoid
        # Просто нормализуем
        if logits.min() >= 0 and logits.max() <= 1:
            # Уже вероятности
            probs = logits / logits.sum()
        else:
            # Обычные логиты — применяем softmax
            e = np.exp(logits - logits.max())
            probs = e / e.sum()

        idx = int(np.argmax(probs))
        confidence = float(probs[idx])
        inference_ms = (time.time() - t0) * 1000

        if confidence >= CONFIDENCE_MIN:
            class_name = CLASS_NAMES[idx]
        else:
            class_name = "empty"

        logger.info("Probs: %s", dict(zip(CLASS_NAMES, [f"{p:.3f}" for p in probs])))
        logger.info(
            "classify → %s (conf=%.2f, %.1f ms)", class_name, confidence, inference_ms
        )
        return class_name, confidence, inference_ms
