"""
Интеграция с ldconsole.exe
"""

import os
import subprocess
from utils.logger import logger


def find_ldconsole():
    """
    Ищет ldconsole.exe на дисках C:\, D:\, E:\

    Returns:
        str: Полный путь к ldconsole.exe или None если не найден
    """

    # Возможные пути
    possible_paths = [
        r"C:\LDPlayer\LDPlayer9\ldconsole.exe",
        r"D:\LDPlayer\LDPlayer9\ldconsole.exe",
        r"E:\LDPlayer\LDPlayer9\ldconsole.exe",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"ldconsole.exe найден: {path}")
            return path

    logger.error("ldconsole.exe не найден на дисках C:\\, D:\\, E\\")
    return None


def scan_emulators(ldconsole_path):
    """
    Сканирует список эмуляторов через ldconsole list2

    Args:
        ldconsole_path: Путь к ldconsole.exe

    Returns:
        list: Список словарей с данными эмуляторов
              [{"id": 0, "name": "LDPlayer", "port": 5554}, ...]
              Пустой список если ошибка
    """

    if not ldconsole_path or not os.path.exists(ldconsole_path):
        logger.error("Некорректный путь к ldconsole.exe")
        return []

    try:
        # Выполнить ldconsole list2
        command = f'"{ldconsole_path}" list2'
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30  # Таймаут 30 секунд
        )

        # Парсинг вывода
        # Формат: "0,LDPlayer\n1,LDPlayer-1\n2,LDPlayer-2\n..."
        emulators = []

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            parts = line.split(',')
            if len(parts) >= 2:
                try:
                    emulator_id = int(parts[0])
                    name = parts[1].strip()
                    port = 5554 + (emulator_id * 2)  # Формула из ТЗ

                    emulators.append({
                        "id": emulator_id,
                        "name": name,
                        "port": port
                    })
                except ValueError:
                    # Пропускаем строки с некорректным форматом
                    continue

        logger.info(f"Найдено эмуляторов: {len(emulators)}")
        return emulators

    except subprocess.TimeoutExpired:
        logger.error("Таймаут при выполнении ldconsole list2")
        return []
    except Exception as e:
        logger.error(f"Ошибка при сканировании эмуляторов: {e}")
        return []


def start_emulator(ldconsole_path, emulator_id):
    """
    Запускает эмулятор по ID

    Args:
        ldconsole_path: Путь к ldconsole.exe
        emulator_id: ID эмулятора
    """
    command = f'"{ldconsole_path}" launch --index {emulator_id}'
    subprocess.run(command, shell=True)
    logger.info(f"Запуск эмулятора id={emulator_id}")


def stop_emulator(ldconsole_path, emulator_id):
    """
    Останавливает эмулятор по ID

    Args:
        ldconsole_path: Путь к ldconsole.exe
        emulator_id: ID эмулятора
    """
    command = f'"{ldconsole_path}" quit --index {emulator_id}'
    subprocess.run(command, shell=True)
    logger.info(f"Остановка эмулятора id={emulator_id}")