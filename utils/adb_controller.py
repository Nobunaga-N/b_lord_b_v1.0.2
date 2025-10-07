"""
Управление ADB командами
"""

import subprocess
import time


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
        print(f"[ERROR] Таймаут при выполнении команды: {command}")
        return ""
    except Exception as e:
        print(f"[ERROR] Ошибка выполнения команды: {e}")
        return ""


def wait_for_adb(port, timeout=90):
    """
    Ожидает готовности ADB подключения

    Args:
        port: порт эмулятора (5554, 5556, ...)
        timeout: максимальное время ожидания в секундах (по умолчанию 90)

    Returns:
        bool: True если ADB готов, False если таймаут
    """

    adb_address = f"127.0.0.1:{port}"
    start_time = time.time()

    print(f"[DEBUG] Ожидание ADB: {adb_address}, timeout={timeout}s")

    while time.time() - start_time < timeout:
        try:
            # Попытка подключения к ADB
            result = execute_command(f"adb connect {adb_address}")

            if "connected" in result.lower() or "already connected" in result.lower():
                # Дополнительная проверка - можем ли выполнять команды
                test_result = execute_command(f"adb -s {adb_address} shell echo 'ok'")

                if "ok" in test_result:
                    print(f"[DEBUG] ADB готов: {adb_address}")
                    return True

        except Exception as e:
            print(f"[DEBUG] ADB не готов: {e}")

        # Ждем 5 секунд перед следующей попыткой
        time.sleep(5)

    print(f"[ERROR] ADB не готов после {timeout}s: {adb_address}")
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
        print(f"[ERROR] Некорректный объект эмулятора: {emulator}")
        return False

    adb_address = f"127.0.0.1:{emulator['port']}"

    # Маппинг клавиш
    KEY_CODES = {
        "ESC": "111",     # KEYCODE_ESCAPE
        "BACK": "4",      # KEYCODE_BACK
        "HOME": "3",      # KEYCODE_HOME
        "ENTER": "66",    # KEYCODE_ENTER
    }

    # Проверка существования клавиши
    if key not in KEY_CODES:
        print(f"[ERROR] Неизвестная клавиша: {key}. Доступны: {list(KEY_CODES.keys())}")
        return False

    keycode = KEY_CODES[key]

    # Выполнить команду
    command = f"adb -s {adb_address} shell input keyevent {keycode}"
    result = execute_command(command)

    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
    print(f"[DEBUG] [{emulator_name}] Нажата клавиша: {key}")

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
        print(f"[ERROR] Некорректный объект эмулятора: {emulator}")
        return False

    # Валидация координат (разрешение 540x960)
    if not (0 <= x <= 540) or not (0 <= y <= 960):
        print(f"[WARNING] Координаты вне экрана: ({x}, {y}). Разрешение: 540x960")

    adb_address = f"127.0.0.1:{emulator['port']}"

    # Выполнить команду
    command = f"adb -s {adb_address} shell input tap {x} {y}"
    result = execute_command(command)

    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
    print(f"[DEBUG] [{emulator_name}] Тап по ({x}, {y})")

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
        print(f"[ERROR] Некорректный объект эмулятора: {emulator}")
        return False

    # Валидация координат (разрешение 540x960)
    coords_valid = True
    if not (0 <= x1 <= 540) or not (0 <= y1 <= 960):
        print(f"[WARNING] Начальные координаты вне экрана: ({x1}, {y1}). Разрешение: 540x960")
        coords_valid = False

    if not (0 <= x2 <= 540) or not (0 <= y2 <= 960):
        print(f"[WARNING] Конечные координаты вне экрана: ({x2}, {y2}). Разрешение: 540x960")
        coords_valid = False

    # Валидация длительности
    if duration < 0:
        print(f"[WARNING] Некорректная длительность: {duration}мс. Установлено 300мс")
        duration = 300

    adb_address = f"127.0.0.1:{emulator['port']}"

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

    print(f"[DEBUG] [{emulator_name}] Свайп {direction}: ({x1},{y1}) → ({x2},{y2}), {duration}мс")

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
        print(f"[ERROR] Некорректный объект эмулятора: {emulator}")
        return False

    adb_address = f"127.0.0.1:{emulator['port']}"
    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    # Формирование команды
    if activity:
        command = f"adb -s {adb_address} shell am start -n {package_name}/{activity}"
    else:
        # Запуск главной активности
        command = f"adb -s {adb_address} shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1"

    print(f"[INFO] [{emulator_name}] Запуск приложения: {package_name}")
    result = execute_command(command)

    # Проверка успешности
    if "Error" in result or "error" in result:
        print(f"[ERROR] [{emulator_name}] Ошибка запуска приложения: {result}")
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

    adb_address = f"127.0.0.1:{emulator['port']}"

    # Получить список запущенных процессов
    command = f"adb -s {adb_address} shell ps"
    result = execute_command(command)

    return package_name in result