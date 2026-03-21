SERIAL_PORT    = "/dev/ttyUSB0"
SERIAL_BAUD    = 115200
MODEL_PATH     = "model/model.tflite"
IMG_SIZE       = (224, 224)
CLASS_NAMES    = ["A", "B", "C", "reject"]
CONFIDENCE_MIN = 0.6
FLASK_HOST     = "0.0.0.0"
FLASK_PORT     = 5000
WEB_PASSWORD   = "1234"
FRAME_WARMUP   = 3

# Маппинг классов → команды Arduino (реальный протокол conveyer.ino)
# A→servo0(101мм), B→servo1(155мм), C→servo2(209мм), reject→конец(300мм)
_CMD_MAP = {"A": "0", "B": "1", "C": "2", "reject": "3"}

# Маппинг REST-команд (из /api/cmd) → Arduino
_REST_MAP = {
    "DROP_A":   "0",
    "DROP_B":   "1",
    "DROP_C":   "2",
    "DROP_REJ": "3",
    "STOP":     "STOP",
}
