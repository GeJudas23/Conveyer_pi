import random
import time
import logging
import numpy as np

from config import CLASS_NAMES, CONFIDENCE_MIN

logger = logging.getLogger(__name__)


class Classifier:
    """
    ЗАГЛУШКА классификатора.

    Возвращает случайный класс с имитацией задержки инференса.
    Для замены на реальный tflite:
      1. pip install tflite-runtime
      2. Раскомментировать блок ниже и удалить метод _stub_run
      3. Положить model/model.tflite

    # from tflite_runtime.interpreter import Interpreter
    # class Classifier:
    #     def __init__(self):
    #         self._interp = Interpreter(model_path=MODEL_PATH)
    #         self._interp.allocate_tensors()
    #         self._inp = self._interp.get_input_details()[0]
    #         self._out = self._interp.get_output_details()[0]
    #
    #     def run(self, frame):
    #         img = Image.fromarray(frame).resize(IMG_SIZE)
    #         x = np.array(img, dtype=np.float32)[np.newaxis] / 255.0
    #         self._interp.set_tensor(self._inp['index'], x)
    #         t0 = time.time()
    #         self._interp.invoke()
    #         inference_ms = (time.time() - t0) * 1000
    #         probs = self._interp.get_tensor(self._out['index'])[0]
    #         idx = int(np.argmax(probs))
    #         confidence = float(probs[idx])
    #         class_name = CLASS_NAMES[idx] if confidence >= CONFIDENCE_MIN else "reject"
    #         return class_name, confidence, inference_ms
    """

    def __init__(self):
        logger.warning(
            "Classifier: STUB mode — model not loaded. "
            "Results are random. Replace with tflite when ready."
        )

    def run(self, frame: np.ndarray) -> tuple[str, float, float]:
        """
        Вернуть (class_name, confidence, inference_ms).
        Заглушка: имитирует инференс ~10–30 мс.
        """
        t0 = time.time()
        time.sleep(random.uniform(0.01, 0.03))

        confidence = random.uniform(0.50, 0.99)
        if confidence < CONFIDENCE_MIN:
            class_name = "reject"
        else:
            # Отдаём предпочтение классам A/B/C (reject встречается реже)
            class_name = random.choices(
                CLASS_NAMES,
                weights=[35, 30, 25, 10],
                k=1,
            )[0]

        inference_ms = (time.time() - t0) * 1000
        logger.debug("Stub classify → %s (conf=%.2f, %.1f ms)",
                     class_name, confidence, inference_ms)
        return class_name, confidence, inference_ms
