import threading
import time
import logging
from config import CLASS_NAMES

logger = logging.getLogger(__name__)

_HISTORY_MAX = 50


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self.last_result: dict = {}
        self.counts: dict = {name: 0 for name in CLASS_NAMES}
        self.total: int = 0
        self.avg_cycle_ms: float = 0.0
        self.status: dict = {"arduino": False, "camera": False, "nn": False}
        self.history: list = []
        self._cycle_ms_sum: float = 0.0

    def update(self, result: dict) -> None:
        """Обновить состояние после одного цикла классификации."""
        with self._lock:
            cls = result.get("class_name", "reject")
            cycle_ms = result.get("cycle_ms", 0.0)

            self.last_result = dict(result)
            if cls in self.counts:
                self.counts[cls] += 1
            self.total += 1
            self._cycle_ms_sum += cycle_ms
            self.avg_cycle_ms = self._cycle_ms_sum / self.total

            self.history.append(dict(result))
            if len(self.history) > _HISTORY_MAX:
                self.history.pop(0)

        logger.debug("State updated: class=%s conf=%.2f cycle=%.0f ms",
                     cls, result.get("confidence", 0), cycle_ms)

    def get_snapshot(self) -> dict:
        """Вернуть потокобезопасный снимок состояния."""
        with self._lock:
            return {
                "last_result":  dict(self.last_result),
                "counts":       dict(self.counts),
                "total":        self.total,
                "avg_cycle_ms": round(self.avg_cycle_ms, 1),
                "status":       dict(self.status),
                "history":      list(self.history[-_HISTORY_MAX:]),
            }

    def reset(self) -> None:
        """Сбросить статистику сессии (статус устройств не сбрасывается)."""
        with self._lock:
            self.last_result = {}
            self.counts = {name: 0 for name in CLASS_NAMES}
            self.total = 0
            self.avg_cycle_ms = 0.0
            self._cycle_ms_sum = 0.0
            self.history = []
        logger.info("Session statistics reset")
