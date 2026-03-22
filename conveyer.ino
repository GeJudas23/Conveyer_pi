#include <Wire.h>
#include <VL53L0X.h>
#include <Adafruit_PWMServoDriver.h>

// Объекты
VL53L0X sensor;
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

// Пины
#define CONVEYOR_PIN 5        // Мотор конвейера (PWM)
#define LIGHT_PIN 6           // Подсветка

// Параметры серво
#define SERVO_MIN 150
#define SERVO_MAX 600
#define SERVO_RETRACT_ANGLE 150   // Серво убрано
#define SERVO_PUSH_ANGLE 10       // Серво выталкивает
#define SERVO_SPEED_DELAY 5       // Задержка между шагами (мс)

// Расстояния от датчика до выталкивателей (мм)
#define DISTANCE_TO_SERVO0 101   // мм до серво 0
#define DISTANCE_TO_SERVO1 155   // мм до серво 1
#define DISTANCE_TO_SERVO2 209   // мм до серво 2
#define DISTANCE_TO_END 300      // мм до конца ленты (слот 3)

// Параметры конвейера
#define MAX_CONVEYOR_SPEED 50.0      // Максимальная скорость: 50 мм/с
#define TRANSPORT_SPEED 50.0         // Скорость транспортировки объекта: 50 мм/с (фиксированная)
#define CONVEYOR_PWM_MAX 255         // PWM значение для максимальной скорости

// Параметры детектирования
#define DETECTION_THRESHOLD 70   // Объект ближе 70мм
#define PUSH_DURATION 500        // Время выталкивания (мс)

// Текущие скорости конвейера
float idle_speed = MAX_CONVEYOR_SPEED;      // Скорость холостого хода (регулируется)
float transport_speed = TRANSPORT_SPEED;    // Скорость транспортировки (фиксированная)
float current_speed = MAX_CONVEYOR_SPEED;   // Текущая активная скорость

int idle_pwm = CONVEYOR_PWM_MAX;       // PWM для холостого хода
int transport_pwm = CONVEYOR_PWM_MAX;  // PWM для транспортировки
int current_pwm = CONVEYOR_PWM_MAX;    // Текущий PWM

// Текущие углы серво (для плавного движения)
int servo_angles[3] = {SERVO_RETRACT_ANGLE, SERVO_RETRACT_ANGLE, SERVO_RETRACT_ANGLE};

// Состояния системы
enum State {
  STOPPED,            // Система остановлена
  SCANNING,           // Сканирование ленты
  OBJECT_DETECTED,    // Объект обнаружен
  WAITING_DECISION,   // Ждём решения по Serial
  MOVING_TO_SERVO,    // Везём к выталкивателю
  PUSHING,            // Выталкивание
  MOVING_TO_END,      // Везём в конец ленты (слот 3)
};

State current_state = SCANNING;
int target_servo = -1;
unsigned long state_timer = 0;
int object_count = 0;

void setup() {
  Serial.begin(115200);
  Wire.begin();

  // Инициализация пинов
  pinMode(CONVEYOR_PIN, OUTPUT);
  pinMode(LIGHT_PIN, OUTPUT);
  digitalWrite(LIGHT_PIN, LOW);

  // Инициализация VL53L0X
  Serial.println("Initializing VL53L0X...");
  if (!sensor.init()) {
    Serial.println("ERROR: VL53L0X init failed!");
    while (1) {
      digitalWrite(LIGHT_PIN, HIGH);
      delay(100);
      digitalWrite(LIGHT_PIN, LOW);
      delay(100);
    }
  }

  sensor.setTimeout(500);
  sensor.setMeasurementTimingBudget(200000);
  sensor.startContinuous(30);

  // Инициализация PCA9685
  Serial.println("Initializing PCA9685...");
  pwm.begin();
  pwm.setPWMFreq(50);

  // Убираем все серво в исходное положение
  Serial.println("Setting servos to retract position...");
  for(int i = 0; i < 3; i++) {
    setServo(i, SERVO_RETRACT_ANGLE);
  }

  delay(500);

  // Рассчитываем PWM для транспортировки
  transport_pwm = (int)((transport_speed / MAX_CONVEYOR_SPEED) * CONVEYOR_PWM_MAX);

  // Запуск конвейера на скорости холостого хода
  setIdleSpeed(idle_speed);
  useIdleSpeed();
  startConveyor();

  printHelp();
  printConfig();
}

void loop() {
  int distance = sensor.readRangeContinuousMillimeters();

  // Проверка команд по Serial
  checkSerialCommands();

  // Машина состояний
  switch(current_state) {

    case STOPPED:
      // Система остановлена
      break;

    case SCANNING:
      // Сканируем ленту на наличие объектов
      if (!sensor.timeoutOccurred() && distance < DETECTION_THRESHOLD) {
        Serial.print("Distance: ");
        Serial.print(distance);
        Serial.println(" mm");
        objectDetected();
      }
      break;

    case WAITING_DECISION:
      // Ждём команду по Serial
      break;

    case MOVING_TO_SERVO:
      // Ждём пока объект доедет до выталкивателя
      if (millis() - state_timer >= calculateTravelTime(target_servo)) {
        stopConveyor();
        pushObject(target_servo);
      }
      break;

    case PUSHING:
      // Ждём окончания выталкивания
      if (millis() - state_timer >= PUSH_DURATION) {
        // Убираем выталкиватель (плавно)
        setServo(target_servo, SERVO_RETRACT_ANGLE);
        delay(300);

        Serial.println("Ready for next object\n");
        useIdleSpeed();  // Возврат на скорость холостого хода
        startConveyor();
        current_state = SCANNING;
        target_servo = -1;
      }
      break;

    case MOVING_TO_END:
      // Везём объект в конец ленты (слот 3)
      if (millis() - state_timer >= calculateTravelTimeToEnd()) {
        stopConveyor();
        Serial.println("Object reached end (slot 3)");
        delay(300);

        Serial.println("Ready for next object\n");
        useIdleSpeed();  // Возврат на скорость холостого хода
        startConveyor();
        current_state = SCANNING;
      }
      break;
  }

  delay(10);
}

// Проверка команд по Serial
void checkSerialCommands() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

      // Команда LIGHT_ON
    if (cmd == "LON") {
      digitalWrite(LIGHT_PIN, HIGH);
      Serial.println("Light ON");
      return;
    }

    // Команда LIGHT_OFF
    if (cmd == "LOFF") {
      digitalWrite(LIGHT_PIN, LOW);
      Serial.println("Light OFF");
      return;
    }

    // Команда STOP - работает всегда
    if (cmd == "STOP" || cmd == "X") {
      emergencyStop();
      return;
    }

    // Команда START - работает всегда
    if (cmd == "START") {
      if (current_state == STOPPED) {
        resumeFromStop();
      } else {
        Serial.println("System already running");
      }
      return;
    }

    // Команда SPEED=XX - работает всегда
    if (cmd.startsWith("SPEED=")) {
      float new_speed = cmd.substring(6).toFloat();
      setIdleSpeed(new_speed);
      // Применяем новую скорость только если в режиме SCANNING
      if (current_state == SCANNING) {
        useIdleSpeed();
        analogWrite(CONVEYOR_PIN, current_pwm);
      }
      return;  // ВАЖНО: выход из функции
    }

    // Команда PWM=XXX - работает всегда
    if (cmd.startsWith("PWM=")) {
      int new_pwm = cmd.substring(4).toInt();
      setIdlePWM(new_pwm);
      // Применяем новый PWM только если в режиме SCANNING
      if (current_state == SCANNING) {
        useIdleSpeed();
        analogWrite(CONVEYOR_PIN, current_pwm);
      }
      return;  // ВАЖНО: выход из функции
    }

    // Команда INFO - работает всегда
    if (cmd == "INFO" || cmd == "I") {
      printConfig();
      return;
    }

    // Команда HELP - работает всегда
    if (cmd == "HELP" || cmd == "H" || cmd == "?") {
      printHelp();
      return;
    }

    // Проверка что система не остановлена (для команд 0/1/2/3/RETRY)
    if (current_state == STOPPED) {
      Serial.println("System STOPPED. Send START to resume");
      return;
    }

    // Команды в режиме WAITING_DECISION
    if (current_state == WAITING_DECISION) {

      // Серво 0
      if (cmd == "0") {
        target_servo = 0;
        Serial.print("Moving to servo 0 (");
        Serial.print(DISTANCE_TO_SERVO0);
        Serial.print(" mm, ");
        Serial.print(calculateTravelTime(0) / 1000.0, 2);
        Serial.println(" sec)");
        moveToServo(0);
        return;
      }

      // Серво 1
      if (cmd == "1") {
        target_servo = 1;
        Serial.print("Moving to servo 1 (");
        Serial.print(DISTANCE_TO_SERVO1);
        Serial.print(" mm, ");
        Serial.print(calculateTravelTime(1) / 1000.0, 2);
        Serial.println(" sec)");
        moveToServo(1);
        return;
      }

      // Серво 2
      if (cmd == "2") {
        target_servo = 2;
        Serial.print("Moving to servo 2 (");
        Serial.print(DISTANCE_TO_SERVO2);
        Serial.print(" mm, ");
        Serial.print(calculateTravelTime(2) / 1000.0, 2);
        Serial.println(" sec)");
        moveToServo(2);
        return;
      }

      // Слот 3 - конец ленты
      if (cmd == "3") {
        Serial.print("Moving to end slot 3 (");
        Serial.print(DISTANCE_TO_END);
        Serial.print(" mm, ");
        Serial.print(calculateTravelTimeToEnd() / 1000.0, 2);
        Serial.println(" sec)");
        moveToEnd();
        return;
      }

      // RETRY
      if (cmd == "RETRY" || cmd == "R") {
        Serial.println(">>> RETRY - Restarting detection <<<");
        useIdleSpeed();
        startConveyor();
        current_state = SCANNING;
        target_servo = -1;
        return;
      }

      // Неизвестная команда в режиме WAITING_DECISION
      Serial.println("Invalid! Use 0/1/2/3 or RETRY");
      return;
    }

    // Если дошли сюда - неизвестная команда в другом состоянии
    // НЕ выводим "Command only available when object detected"
    // Просто игнорируем или выводим общую ошибку
    Serial.print("Unknown command: ");
    Serial.println(cmd);
  }
}

// Установить скорость холостого хода
void setIdleSpeed(float speed_mm_s) {
  speed_mm_s = constrain(speed_mm_s, 0, MAX_CONVEYOR_SPEED);
  idle_speed = speed_mm_s;
  idle_pwm = (int)((idle_speed / MAX_CONVEYOR_SPEED) * CONVEYOR_PWM_MAX);

  Serial.print("Idle speed set to ");
  Serial.print(idle_speed, 1);
  Serial.print(" mm/s (PWM: ");
  Serial.print(idle_pwm);
  Serial.println(")");
}

// Установить PWM холостого хода напрямую
void setIdlePWM(int pwm_value) {
  pwm_value = constrain(pwm_value, 0, 255);
  idle_pwm = pwm_value;
  idle_speed = (pwm_value / (float)CONVEYOR_PWM_MAX) * MAX_CONVEYOR_SPEED;

  Serial.print("Idle PWM set to ");
  Serial.print(idle_pwm);
  Serial.print(" (speed: ");
  Serial.print(idle_speed, 1);
  Serial.println(" mm/s)");
}

// Использовать скорость холостого хода
void useIdleSpeed() {
  current_speed = idle_speed;
  current_pwm = idle_pwm;
}

// Использовать скорость транспортировки
void useTransportSpeed() {
  current_speed = transport_speed;
  current_pwm = transport_pwm;
}

// Плавное движение серво
void setServoSmooth(int channel, int target_angle) {
  target_angle = constrain(target_angle, 0, 180);
  int current = servo_angles[channel];

  if (current < target_angle) {
    // Выдвигаем
    for(int angle = current; angle <= target_angle; angle++) {
      int pulse = map(angle, 0, 180, SERVO_MIN, SERVO_MAX);
      pwm.setPWM(channel, 0, pulse);
      delay(SERVO_SPEED_DELAY);
    }
  } else {
    // Убираем
    for(int angle = current; angle >= target_angle; angle--) {
      int pulse = map(angle, 0, 180, SERVO_MIN, SERVO_MAX);
      pwm.setPWM(channel, 0, pulse);
      delay(SERVO_SPEED_DELAY);
    }
  }

  servo_angles[channel] = target_angle;
}

// Управление серво (использует плавное движение)
void setServo(int channel, int angle) {
  setServoSmooth(channel, angle);
}

// Расчёт времени движения до серво (мс) - использует скорость транспортировки
unsigned long calculateTravelTime(int servo_num) {
  float distance_mm = 0;
  switch(servo_num) {
    case 0: distance_mm = DISTANCE_TO_SERVO0; break;
    case 1: distance_mm = DISTANCE_TO_SERVO1; break;
    case 2: distance_mm = DISTANCE_TO_SERVO2; break;
  }
  float time_sec = distance_mm / transport_speed;  // Используем фиксированную скорость транспортировки
  return (unsigned long)(time_sec * 1000);
}

// Расчёт времени до конца ленты (мс) - использует скорость транспортировки
unsigned long calculateTravelTimeToEnd() {
  float time_sec = DISTANCE_TO_END / transport_speed;  // Используем фиксированную скорость транспортировки
  return (unsigned long)(time_sec * 1000);
}

// Аварийная остановка
void emergencyStop() {
  current_state = STOPPED;
  stopConveyor();
  digitalWrite(LIGHT_PIN, LOW);

  Serial.println("\n!!! EMERGENCY STOP !!!");
  Serial.println("Send START to resume\n");
}

// Возобновление работы
void resumeFromStop() {
  Serial.println("Resuming...");

  // Плавно убираем все серво
  for(int i = 0; i < 3; i++) {
    setServo(i, SERVO_RETRACT_ANGLE);
  }

  target_servo = -1;
 // digitalWrite(LIGHT_PIN, LOW);
  current_state = SCANNING;
  useIdleSpeed();  // Возврат на скорость холостого хода
  startConveyor();

  Serial.println("System RESUMED\n");
}

// Обнаружен объект
void objectDetected() {
  object_count++;
  stopConveyor();

  Serial.println("\n==================");
  Serial.print("OBJECT #");
  Serial.print(object_count);
  Serial.println(" DETECTED");
  Serial.println("==================");
  Serial.println("READY: Send 0/1/2 (servo), 3 (end), or RETRY");

  current_state = WAITING_DECISION;
  state_timer = millis();
}

// Начать движение к выталкивателю
void moveToServo(int servo_num) {
  target_servo = servo_num;
  useTransportSpeed();  // Переключаемся на скорость транспортировки
  startConveyor();
  current_state = MOVING_TO_SERVO;
  state_timer = millis();
}

// Начать движение в конец (слот 3)
void moveToEnd() {
  useTransportSpeed();  // Переключаемся на скорость транспортировки
  startConveyor();
  current_state = MOVING_TO_END;
  state_timer = millis();
}

// Выталкивание объекта
void pushObject(int servo_num) {
  Serial.print(">>> Pushing at servo ");
  Serial.print(servo_num);
  Serial.println(" <<<");

  // Плавно выталкиваем
  setServo(servo_num, SERVO_PUSH_ANGLE);

  current_state = PUSHING;
  state_timer = millis();
}

// Управление конвейером
void startConveyor() {
  analogWrite(CONVEYOR_PIN, current_pwm);
}

void stopConveyor() {
  analogWrite(CONVEYOR_PIN, 0);
}

// Вывод конфигурации
void printConfig() {
  Serial.println("\n=== CONFIGURATION ===");
  Serial.print("Idle speed: ");
  Serial.print(idle_speed, 1);
  Serial.print(" mm/s (PWM: ");
  Serial.print(idle_pwm);
  Serial.println(")");
  Serial.print("Transport speed: ");
  Serial.print(transport_speed, 1);
  Serial.print(" mm/s (PWM: ");
  Serial.print(transport_pwm);
  Serial.println(") [FIXED]");
  Serial.print("Detection: <");
  Serial.print(DETECTION_THRESHOLD);
  Serial.println(" mm");
  Serial.print("Servo speed delay: ");
  Serial.print(SERVO_SPEED_DELAY);
  Serial.println(" ms/step");
  Serial.println("");
  Serial.println("Slots (at transport speed):");
  Serial.print("  0: ");
  Serial.print(DISTANCE_TO_SERVO0);
  Serial.print(" mm (");
  Serial.print(calculateTravelTime(0) / 1000.0, 2);
  Serial.println(" sec)");
  Serial.print("  1: ");
  Serial.print(DISTANCE_TO_SERVO1);
  Serial.print(" mm (");
  Serial.print(calculateTravelTime(1) / 1000.0, 2);
  Serial.println(" sec)");
  Serial.print("  2: ");
  Serial.print(DISTANCE_TO_SERVO2);
  Serial.print(" mm (");
  Serial.print(calculateTravelTime(2) / 1000.0, 2);
  Serial.println(" sec)");
  Serial.print("  3: ");
  Serial.print(DISTANCE_TO_END);
  Serial.print(" mm (");
  Serial.print(calculateTravelTimeToEnd() / 1000.0, 2);
  Serial.println(" sec) [END]");
  Serial.println("=====================\n");
}

// Справка
void printHelp() {
  Serial.println("\n=== CONVEYOR SORTER ===");
  Serial.println("COMMANDS:");
  Serial.println("  0         - Push to slot 0 (servo 0)");
  Serial.println("  1         - Push to slot 1 (servo 1)");
  Serial.println("  2         - Push to slot 2 (servo 2)");
  Serial.println("  3         - Send to end (no push)");
  Serial.println("  RETRY/R   - Retry detection");
  Serial.println("  STOP/X    - Emergency stop");
  Serial.println("  START     - Resume");
  Serial.println("  SPEED=XX  - Set idle speed (0-50 mm/s)");
  Serial.println("  PWM=XXX   - Set idle PWM (0-255)");
  Serial.println("  INFO/I    - Show config");
  Serial.println("  HELP/?    - Show this help");
  Serial.println("========================\n");
}
