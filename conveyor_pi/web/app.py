import logging

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

from config import FLASK_HOST, FLASK_PORT, WEB_PASSWORD

logger = logging.getLogger(__name__)


def create_app(state, serial_manager):
    """
    Создать Flask-приложение и SocketIO.

    Возвращает (app, socketio).
    serial_manager может быть None при инициализации —
    main.py устанавливает его через app.serial_manager после создания.
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = "conveyor-secret-key"
    app.serial_manager = serial_manager

    socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

    # ──────────────────────────────────────────────
    # REST endpoints
    # ──────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/state")
    def api_state():
        return jsonify(state.get_snapshot())

    @app.route("/api/cmd", methods=["POST"])
    def api_cmd():
        password = request.headers.get("X-Password", "")
        if password != WEB_PASSWORD:
            logger.warning("api/cmd: wrong password from %s", request.remote_addr)
            return jsonify({"error": "Forbidden"}), 403

        data = request.get_json(silent=True) or {}
        cmd = data.get("cmd", "")
        if not cmd:
            return jsonify({"error": "Missing cmd"}), 400

        mgr = app.serial_manager
        if mgr is None:
            return jsonify({"error": "Serial manager not ready"}), 503

        mgr.send_manual_cmd(cmd)
        logger.info("api/cmd: %s from %s", cmd, request.remote_addr)
        return jsonify({"ok": True, "cmd": cmd})

    @app.route("/api/reset", methods=["POST"])
    def api_reset():
        state.reset()
        logger.info("Session reset via API from %s", request.remote_addr)
        return jsonify({"ok": True})

    # ──────────────────────────────────────────────
    # SocketIO events
    # ──────────────────────────────────────────────

    @socketio.on("connect")
    def on_connect():
        logger.debug("Client connected: %s", request.sid)
        # Отправить текущий статус сразу при подключении
        socketio.emit("status", state.status, to=request.sid)

    @socketio.on("disconnect")
    def on_disconnect():
        logger.debug("Client disconnected: %s", request.sid)

    return app, socketio
