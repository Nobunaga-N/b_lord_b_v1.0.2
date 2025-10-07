"""
Управление ADB командами
"""

import subprocess
import time
from utils.logger import logger


def execute_command(command):
    """
    Выполняет команду в shell

    Args:
        command: строка команды для выполнения

    Returns:
        str: Вывод команды (stdout)
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30  # Таймаут 30 секунд
        )

        # Вернуть stdout, даже если команда завершилась с ошибкой
        return result.stdout

    except subprocess.TimeoutExpired:
        logger.error(f"Таймаут при выполнении команды: {command}")
        return ""
    except Exception as e:
        logger.error(f"Ошибка выполнения команды: {e}")
        return ""

def get_adb_device(port):
    """
    Определяет правильный ADB адрес устройства для данного порта

    LDPlayer эмуляторы обычно отображаются как emulator-5554, emulator-5556 и т.д.
    Эта функция проверяет какой адрес использовать.

    Args:
        port: порт эмулятора (5554, 5556, ...)

    Returns:
        str: ADB адрес устройства (например "emulator-5556" или "127.0.0.1:5556")
    """
    # Возможные адреса
    emulator_address = f"emulator-{port}"
    tcp_address = f"127.0.0.1:{port}"

    # Проверить adb devices
    devices_result = execute_command("adb devices")

    # Проверяем оба формата
    if emulator_address in devices_result and "device" in devices_result:
        return emulator_address
    elif tcp_address in devices_result and "device" in devices_result:
        return tcp_address
    else:
        # По умолчанию возвращаем emulator-адрес (для LDPlayer)
        return emulator_address

def wait_for_adb(port, timeout=90):
    """
    Ожидает готовности ADB подключения

    Args:
        port: порт эмулятора (5554, 5556, ...)
        timeout: максимальное время ожидания в секундах (по умолчанию 90)

    Returns:
        bool: True если ADB готов, False если таймаут
    """

    # Возможные адреса устройства
    tcp_address = f"127.0.0.1:{port}"
    emulator_address = f"emulator-{port}"  # LDPlayer использует такой формат

    start_time = time.time()
    attempt = 0

    logger.info(f"Ожидание ADB для порта {port} (проверю: {tcp_address} и {emulator_address})")

    while time.time() - start_time < timeout:
        attempt += 1
        elapsed = int(time.time() - start_time)

        try:
            logger.debug(f"[port:{port}] Попытка {attempt} (прошло {elapsed}s)")

            # ШАГ 1: Проверить список подключенных устройств
            devices_result = execute_command("adb devices")
            logger.debug(f"[port:{port}] adb devices:\n{devices_result.strip()}")

            # Проверяем оба формата адреса
            device_found = None

            if emulator_address in devices_result and "device" in devices_result:
                device_found = emulator_address
                logger.debug(f"[port:{port}] Найдено устройство: {device_found}")
            elif tcp_address in devices_result and "device" in devices_result:
                device_found = tcp_address
                logger.debug(f"[port:{port}] Найдено устройство: {device_found}")

            # ШАГ 2: Если устройство найдено - проверить команды
            if device_found:
                logger.debug(f"[port:{port}] Устройство {device_found} найдено, проверяю команды...")

                test_result = execute_command(f"adb -s {device_found} shell echo 'ok'")
                logger.debug(f"[port:{port}] adb shell echo вернул: '{test_result.strip()}'")

                if "ok" in test_result:
                    logger.success(f"ADB готов: {device_found} (попытка {attempt}, {elapsed}s)")
                    return True
                else:
                    logger.debug(f"[port:{port}] Shell команда не работает, ожидание...")

            # ШАГ 3: Если устройство не найдено - попробовать adb connect
            else:
                logger.debug(f"[port:{port}] Устройство не найдено в adb devices, пробую adb connect...")
                connect_result = execute_command(f"adb connect {tcp_address}")
                logger.debug(f"[port:{port}] adb connect вернул: {connect_result.strip()[:100]}")

                if "connected" in connect_result.lower() or "already connected" in connect_result.lower():
                    logger.debug(f"[port:{port}] Подключение через connect установлено")
                    # Проверим на следующей итерации
                else:
                    logger.debug(f"[port:{port}] Подключение не установлено, ожидание...")

        except Exception as e:
            logger.debug(f"[port:{port}] Ошибка на попытке {attempt}: {e}")

        # Ждем 5 секунд перед следующей попыткой
        logger.debug(f"[port:{port}] Ожидание 5 секунд перед следующей попыткой...")
        time.sleep(5)

    logger.error(f"ADB не готов после {timeout}s ({attempt} попыток) для порта {port}")
    return False


def press_key(emulator, key):
    """
    Нажимает клавишу на эмуляторе

    Args:
        emulator: словарь с данными эмулятора (должен содержать 'port' и 'name')
        key: название клавиши ("ESC", "BACK", "HOME", "ENTER")

    Returns:
        bool: True если команда выполнена успешно
    """

    # Валидация входных данных
    if not isinstance(emulator, dict) or 'port' not in emulator:
        logger.error(f"Некорректный объект эмулятора: {emulator}")
        return False

    # ИСПРАВЛЕНО: Используем get_adb_device() вместо жестко заданного адреса
    adb_address = get_adb_device(emulator['port'])

    # Маппинг клавиш
    KEY_CODES = {
        "ESC": "111",     # KEYCODE_ESCAPE
        "BACK": "4",      # KEYCODE_BACK
        "HOME": "3",      # KEYCODE_HOME
        "ENTER": "66",    # KEYCODE_ENTER
    }

    # Проверка существования клавиши
    if key not in KEY_CODES:
        logger.error(f"Неизвестная клавиша: {key}. Доступны: {list(KEY_CODES.keys())}")
        return False

    keycode = KEY_CODES[key]

    # Выполнить команду
    command = f"adb -s {adb_address} shell input keyevent {keycode}"
    result = execute_command(command)

    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
    logger.debug(f"[{emulator_name}] Нажата клавиша: {key} (устройство: {adb_address})")

    return True


def tap(emulator, x, y):
    """
    Тап по координатам на экране

    Args:
        emulator: словарь с данными эмулятора (должен содержать 'port' и 'name')
        x: координата X (для разрешения 540x960)
        y: координата Y (для разрешения 540x960)

    Returns:
        bool: True если команда выполнена успешно
    """

    # Валидация входных данных
    if not isinstance(emulator, dict) or 'port' not in emulator:
        logger.error(f"Некорректный объект эмулятора: {emulator}")
        return False

    # Валидация координат (разрешение 540x960)
    if not (0 <= x <= 540) or not (0 <= y <= 960):
        logger.warning(f"Координаты вне экрана: ({x}, {y}). Разрешение: 540x960")

    # ИСПРАВЛЕНО: Используем get_adb_device() вместо жестко заданного адреса
    adb_address = get_adb_device(emulator['port'])

    # Выполнить команду
    command = f"adb -s {adb_address} shell input tap {x} {y}"
    result = execute_command(command)

    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
    logger.debug(f"[{emulator_name}] Тап по ({x}, {y}) (устройство: {adb_address})")

    return True


def swipe(emulator, x1, y1, x2, y2, duration=300):
    """
    Выполняет свайп (проведение пальцем) по экрану

    Args:
        emulator: словарь с данными эмулятора (должен содержать 'port' и 'name')
        x1: начальная координата X (для разрешения 540x960)
        y1: начальная координата Y (для разрешения 540x960)
        x2: конечная координата X (для разрешения 540x960)
        y2: конечная координата Y (для разрешения 540x960)
        duration: длительность свайпа в миллисекундах (по умолчанию 300мс)

    Returns:
        bool: True если команда выполнена успешно
    """

    # Валидация входных данных
    if not isinstance(emulator, dict) or 'port' not in emulator:
        logger.error(f"Некорректный объект эмулятора: {emulator}")
        return False

    # Валидация координат (разрешение 540x960)
    coords_valid = True
    if not (0 <= x1 <= 540) or not (0 <= y1 <= 960):
        logger.warning(f"Начальные координаты вне экрана: ({x1}, {y1}). Разрешение: 540x960")
        coords_valid = False

    if not (0 <= x2 <= 540) or not (0 <= y2 <= 960):
        logger.warning(f"Конечные координаты вне экрана: ({x2}, {y2}). Разрешение: 540x960")
        coords_valid = False

    # Валидация длительности
    if duration < 0:
        logger.warning(f"Некорректная длительность: {duration}мс. Установлено 300мс")
        duration = 300

    # ИСПРАВЛЕНО: Используем get_adb_device() вместо жестко заданного адреса
    adb_address = get_adb_device(emulator['port'])

    # Выполнить команду
    command = f"adb -s {adb_address} shell input swipe {x1} {y1} {x2} {y2} {duration}"
    result = execute_command(command)

    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    # Определение направления для логирования
    direction = ""
    if abs(x2 - x1) > abs(y2 - y1):
        # Горизонтальный свайп
        direction = "вправо" if x2 > x1 else "влево"
    else:
        # Вертикальный свайп
        direction = "вниз" if y2 > y1 else "вверх"

    logger.debug(f"[{emulator_name}] Свайп {direction}: ({x1},{y1}) → ({x2},{y2}), {duration}мс (устройство: {adb_address})")

    return True


def launch_app(emulator, package_name, activity=None):
    """
    Запускает приложение на эмуляторе

    Args:
        emulator: словарь с данными эмулятора
        package_name: имя пакета приложения (например "com.allstarunion.beastlord")
        activity: активность для запуска (если None, запускается главная активность)

    Returns:
        bool: True если запуск успешен
    """

    if not isinstance(emulator, dict) or 'port' not in emulator:
        logger.error(f"Некорректный объект эмулятора: {emulator}")
        return False

    # ИСПРАВЛЕНО: Используем get_adb_device() вместо жестко заданного адреса
    adb_address = get_adb_device(emulator['port'])
    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    # Формирование команды
    if activity:
        command = f"adb -s {adb_address} shell am start -n {package_name}/{activity}"
    else:
        # Запуск главной активности
        command = f"adb -s {adb_address} shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1"

    logger.info(f"[{emulator_name}] Запуск приложения: {package_name}")
    result = execute_command(command)

    # Проверка успешности
    if "Error" in result or "error" in result:
        logger.error(f"[{emulator_name}] Ошибка запуска приложения: {result}")
        return False

    return True


def is_app_running(emulator, package_name):
    """
    Проверяет запущено ли приложение

    Args:
        emulator: словарь с данными эмулятора
        package_name: имя пакета приложения

    Returns:
        bool: True если приложение запущено
    """

    if not isinstance(emulator, dict) or 'port' not in emulator:
        return False

    # ИСПРАВЛЕНО: Используем get_adb_device() вместо жестко заданного адреса
    adb_address = get_adb_device(emulator['port'])

    # Получить список запущенных процессов
    command = f"adb -s {adb_address} shell ps"
    result = execute_command(command)

    return package_name in result