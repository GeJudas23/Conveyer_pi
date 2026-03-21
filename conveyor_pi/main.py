import logging
import signal
import sys
import threading

import eventlet
eventlet.monkey_patch()

from config import FLASK_HOST, FLASK_PORT
from camera import Camera
from classifier import Classifier
from state import AppState
from serial_manager import SerialManager
from web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=== Conveyor Pi starting ===")

    # ── Инициализация компонентов ────────────────
    camera = Camera()

    classifier = Classifier()

    state = AppState()
    state.status["camera"] = True
    state.status["nn"] = True  # stub всегда "работает"

    # ── Flask + SocketIO (serial_manager добавим позже) ──
    app, socketio = create_app(state, serial_manager=None)

    # ── Serial manager ───────────────────────────
    serial_manager = SerialManager(camera, classifier, state, socketio)
    app.serial_manager = serial_manager  # подключаем к Flask

    # ── Graceful shutdown ────────────────────────
    def shutdown(sig, frame):
        logger.info("Shutdown signal received (%s)", signal.Signals(sig).name)
        serial_manager.close()
        camera.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # ── Flask в daemon-потоке ────────────────────
    flask_thread = threading.Thread(
        target=lambda: socketio.run(
            app,
            host=FLASK_HOST,
            port=FLASK_PORT,
            use_reloader=False,
            log_output=False,
        ),
        daemon=True,
    )
    flask_thread.start()
    logger.info("Web dashboard: http://%s:%d", FLASK_HOST, FLASK_PORT)

    # ── Основной цикл (блокирует main thread) ────
    serial_manager.run_loop()

    logger.info("=== Conveyor Pi stopped ===")


if __name__ == "__main__":
    main()
