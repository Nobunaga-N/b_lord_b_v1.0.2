"""
Настройка логирования через loguru
"""

import os
import sys
import subprocess
from loguru import logger


def setup_logger():
    """
    Настраивает loguru для проекта

    Формат: [HH:MM:SS] LEVEL | Сообщение
    Цвета:
    - INFO: белый/серый
    - SUCCESS: зелёный
    - WARNING: жёлтый
    - ERROR: красный
    - DEBUG: синий
    """

    # Удаляем дефолтный обработчик
    logger.remove()

    # Создаём папку для логов если не существует
    os.makedirs("data/logs", exist_ok=True)

    # Формат времени и сообщения
    log_format = (
        "<green>[{time:HH:mm:ss}]</green> "
        "<level>{level: <8}</level> | "
        "<level>{message}</level>"
    )

    # Добавляем обработчик в файл (с ANSI цветами)
    logger.add(
        "data/logs/bot.log",
        format=log_format,
        level="DEBUG",
        rotation="10 MB",  # Ротация при достижении 10 МБ
        retention="7 days",  # Хранить логи 7 дней
        compression="zip",  # Сжимать старые логи
        colorize=True,  # ANSI коды цветов в файле
        backtrace=True,  # Полный traceback при ошибках
        diagnose=True,  # Диагностическая информация
        enqueue=True,  # Потокобезопасность
    )

    # Добавляем обработчик в консоль (для разработки)
    logger.add(
        sys.stdout,
        format=log_format,
        level="DEBUG",
        colorize=True,
    )

    logger.info("Логирование настроено")
    logger.debug(f"Файл логов: data/logs/bot.log")


def open_log_terminal():
    """
    Открывает Windows Terminal с логами в режиме tail -f

    Пытается использовать Windows Terminal (wt.exe),
    если не найден - использует cmd.exe как fallback

    Returns:
        bool: True если терминал открыт успешно
    """

    log_path = os.path.abspath("data/logs/bot.log")

    # Убедиться что файл логов существует
    if not os.path.exists(log_path):
        # Создать пустой файл
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        open(log_path, 'a').close()

    try:
        # Попытка 1: Windows Terminal (wt.exe)
        # Используем shell=True для корректной работы wt.exe
        command = f'wt.exe powershell -NoExit -Command "Get-Content -Path \'{log_path}\' -Wait -Tail 50"'

        subprocess.Popen(
            command,
            shell=True
        )

        logger.success("Windows Terminal открыт с логами")
        return True

    except FileNotFoundError:
        # Fallback: CMD с PowerShell
        logger.warning("Windows Terminal не найден, использую CMD")

        try:
            command = f'start powershell -NoExit -Command "Get-Content -Path \'{log_path}\' -Wait -Tail 50"'

            subprocess.Popen(command, shell=True)
            logger.success("CMD с PowerShell открыт с логами")
            return True

        except Exception as e:
            logger.error(f"Не удалось открыть терминал с логами: {e}")
            return False

    except Exception as e:
        logger.error(f"Ошибка при открытии Windows Terminal: {e}")

        # Попытка fallback на CMD
        logger.warning("Пробую fallback на CMD...")
        try:
            command = f'start powershell -NoExit -Command "Get-Content -Path \'{log_path}\' -Wait -Tail 50"'
            subprocess.Popen(command, shell=True)
            logger.success("CMD с PowerShell открыт с логами")
            return True
        except Exception as e2:
            logger.error(f"Не удалось открыть терминал с логами: {e2}")
            return False


def get_logger():
    """
    Возвращает настроенный логгер

    Returns:
        logger: Объект loguru logger
    """
    return logger


# При импорте автоматически настроить логгер
setup_logger()