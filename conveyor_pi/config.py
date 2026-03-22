SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 115200
MODEL_PATH = "model/stand-nn-cls.onnx"
IMG_SIZE = (224, 224)
CLASS_NAMES = ["circle", "cross", "empty", "heart", "star"]
CONFIDENCE_MIN = 0.35
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
WEB_PASSWORD = "1234"
FRAME_WARMUP = 3

# circle→0, star→1, heart→2, всё остальное→брак(3)
_CMD_MAP = {
    "circle": "0",
    "star": "1",
    "heart": "2",
    "cross": "3",
    "empty": "3",
}

_REST_MAP = {
    "START": "START",
    "STOP": "STOP",
}
