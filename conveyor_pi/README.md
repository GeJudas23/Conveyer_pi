# Conveyor Pi

Система классификации объектов на конвейере.
Raspberry Pi 4 + Pi Camera 3 → нейросеть → Serial → Arduino → сервоприводы.

---

## Требования

- Raspberry Pi 4, Raspberry Pi OS Bookworm (64-bit)
- Pi Camera 3 (MIPI CSI)
- Arduino с прошивкой `conveyer.ino`, подключённый по USB

---

## Установка зависимостей

```bash
# Системные пакеты (picamera2 и libcamera)
sudo apt-get update
sudo apt-get install -y python3-picamera2 python3-pip

# Python-пакеты
cd /home/pi/conveyor_pi
pip3 install -r requirements.txt
```

> **Примечание:** `picamera2` лучше устанавливать через `apt`, а не pip.
> `tflite-runtime` устанавливается через pip и требует arm64-колёса:
> `pip3 install tflite-runtime`

---

## Как положить модель

Скопируйте файл модели в директорию `model/`:

```bash
cp /путь/к/model.tflite /home/pi/conveyor_pi/model/model.tflite
```

Пока модель не подложена, классификатор работает в **режиме заглушки** (случайные результаты).

---

## Настройка Serial-порта

По умолчанию используется `/dev/ttyUSB0`.
Чтобы изменить порт или baudrate — отредактируйте `config.py`:

```python
SERIAL_PORT = "/dev/ttyUSB0"   # или /dev/ttyAMA0
SERIAL_BAUD = 115200
```

Убедитесь, что пользователь `pi` имеет доступ к порту:

```bash
sudo usermod -a -G dialout pi
# Перелогиниться или:
newgrp dialout
```

---

## Запуск вручную

```bash
cd /home/pi/conveyor_pi
python3 main.py
```

Веб-дашборд откроется на `http://<ip-pi>:5000`.
Пароль для команд по умолчанию: `1234` (меняется в `config.py` → `WEB_PASSWORD`).

---

## Автозапуск через systemd

```bash
# Скопировать юнит
sudo cp /home/pi/conveyor_pi/conveyor.service /etc/systemd/system/

# Активировать
sudo systemctl daemon-reload
sudo systemctl enable conveyor
sudo systemctl start conveyor

# Статус и логи
sudo systemctl status conveyor
journalctl -u conveyor -f
```

---

## Протокол Serial (Arduino ↔ Pi)

Конвейер использует **реальный протокол** из `conveyer.ino`:

| Arduino → Pi | Интерпретация |
|---|---|
| `READY: Send 0/1/2...` | Объект на позиции, готов к сканированию |
| `Ready for next object` | Цикл завершён |
| `ERROR...` | Ошибка Arduino |

| Pi → Arduino | Действие |
|---|---|
| `0\n` | Сбросить в лоток A (servo 0, 101 мм) |
| `1\n` | Сбросить в лоток B (servo 1, 155 мм) |
| `2\n` | Сбросить в лоток C (servo 2, 209 мм) |
| `3\n` | Отправить в конец ленты (reject, 300 мм) |
| `STOP\n` | Аварийная остановка |

---

## Структура проекта

```
conveyor_pi/
├── main.py             # точка входа
├── config.py           # все константы
├── state.py            # общее состояние (thread-safe)
├── camera.py           # захват через picamera2
├── classifier.py       # TFLite инференс (сейчас — заглушка)
├── serial_manager.py   # UART-связь с Arduino
├── requirements.txt
├── conveyor.service    # systemd unit
├── model/
│   └── model.tflite    # положить сюда модель
└── web/
    ├── app.py          # Flask + SocketIO
    ├── templates/
    │   └── index.html  # веб-дашборд
    └── static/
```
