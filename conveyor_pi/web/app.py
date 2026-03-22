import logging
import time

from flask import Flask, Response, jsonify, render_template, request
from flask_socketio import SocketIO

from config import FLASK_HOST, FLASK_PORT, WEB_PASSWORD

logger = logging.getLogger(__name__)


def create_app(state, serial_manager):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = "conveyor-secret-key"
    app.serial_manager = serial_manager

    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/state")
    def api_state():
        return jsonify(state.get_snapshot())

    @app.route("/video_feed")
    def video_feed():
        """MJPEG стрим с камеры."""

        def generate():
            cam = app.camera
            while True:
                try:
                    frame = cam.capture()
                    jpeg = cam.frame_to_jpeg(frame, quality=70)
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                    )
                except Exception as e:
                    logger.warning("Stream frame error: %s", e)
                    time.sleep(0.1)

        return Response(
            generate(), mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    @app.route("/api/cmd", methods=["POST"])
    def api_cmd():
        password = request.headers.get("X-Password", "")
        if password != WEB_PASSWORD:
            return jsonify({"error": "Forbidden"}), 403
        data = request.get_json(silent=True) or {}
        cmd = data.get("cmd", "")
        if not cmd:
            return jsonify({"error": "Missing cmd"}), 400
        mgr = app.serial_manager
        if mgr is None:
            return jsonify({"error": "Serial manager not ready"}), 503
        mgr.send_manual_cmd(cmd)
        return jsonify({"ok": True, "cmd": cmd})

    @app.route("/api/reset", methods=["POST"])
    def api_reset():
        state.reset()
        socketio.emit("state_reset", {})
        return jsonify({"ok": True})

    @socketio.on("connect")
    def on_connect():
        logger.debug("Client connected: %s", request.sid)
        # Небольшая задержка чтобы serial_manager успел обновить статус
        import time

        time.sleep(0.2)
        snap = state.get_snapshot()
        socketio.emit("status", snap["status"], to=request.sid)
        socketio.emit("init_state", snap, to=request.sid)

    @socketio.on("disconnect")
    def on_disconnect():
        logger.debug("Client disconnected: %s", request.sid)

    return app, socketio
