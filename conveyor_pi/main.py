import logging
import signal
import sys
import threading
import time

import serial as pyserial

from config import FLASK_HOST, FLASK_PORT, SERIAL_BAUD, SERIAL_PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from camera import Camera
from classifier import Classifier
from serial_manager import SerialManager
from state import AppState
from web.app import create_app


def main():
    logger.info("=== Conveyor Pi starting ===")

    logger.info("Opening serial port %s...", SERIAL_PORT)
    try:
        ser = pyserial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=3)
        logger.info("Waiting for Arduino to initialize...")
        deadline = time.time() + 10
        while time.time() < deadline:
            line = ser.readline().decode(errors="replace").strip()
            if line:
                logger.debug("Arduino init: %s", line)
            if "=====================" in line:
                logger.info("Arduino ready")
                break
    except Exception as e:
        logger.warning("Could not open serial early: %s — light control disabled", e)
        ser = None

    camera = Camera(serial_port=ser)
    classifier = Classifier()

    state = AppState()
    state.status["camera"] = True
    state.status["nn"] = True

    app, socketio = create_app(state, serial_manager=None)
    app.camera = camera

    serial_manager = SerialManager(camera, classifier, state, socketio, ser=ser)
    app.serial_manager = serial_manager

    def shutdown(sig, frame):
        logger.info("Shutdown signal received (%s)", signal.Signals(sig).name)
        serial_manager.close()
        camera.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    flask_thread = threading.Thread(
        target=lambda: socketio.run(
            app,
            host=FLASK_HOST,
            port=FLASK_PORT,
            use_reloader=False,
            log_output=False,
            allow_unsafe_werkzeug=True,
        ),
        daemon=True,
    )
    flask_thread.start()
    logger.info("Web dashboard: http://%s:%d", FLASK_HOST, FLASK_PORT)

    # Ждём пока Flask поднимется и шлём актуальный статус
    def delayed_status():
        time.sleep(2)
        state.status["arduino"] = serial_manager._is_open()
        logger.info("Delayed status emit: %s", state.status)
        socketio.emit("status", state.status)

    threading.Thread(target=delayed_status, daemon=True).start()

    serial_manager.run_loop()

    logger.info("=== Conveyor Pi stopped ===")


if __name__ == "__main__":
    main()
