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

    # ⚠️ КРИТИЧНО: Настройка UTF-8 для Windows консоли
    if sys.platform == 'win32':
        try:
            # Попытка установить UTF-8 кодировку для консоли
            import os
            os.system('chcp 65001 > nul 2>&1')

            # Перенастроить stdout/stderr на UTF-8
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding='utf-8')
        except Exception as e:
            print(f"⚠️ Не удалось настроить UTF-8: {e}")

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

    Приоритет:
    1. Windows Terminal + PowerShell 7+ (pwsh)
    2. Windows Terminal + PowerShell 5 (powershell)
    3. PowerShell 7+ отдельное окно (pwsh)
    4. PowerShell 5 отдельное окно (powershell)

    Returns:
        bool: True если терминал открыт успешно
    """

    log_path = os.path.abspath("data/logs/bot.log")

    # Убедиться что файл логов существует
    if not os.path.exists(log_path):
        # Создать пустой файл
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        open(log_path, 'a', encoding='utf-8').close()

    # Создаём временный PowerShell скрипт
    script_path = os.path.abspath("data/logs/tail_logs.ps1")

    # PowerShell скрипт с правильной кодировкой
    ps_script_content = f"""# Установка кодировки UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Красивый разделитель с временем запуска
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "    🚀 Beast Lord Bot - Логи в реальном времени" -ForegroundColor Green
Write-Host "    📅 Запуск терминала: $timestamp" -ForegroundColor Yellow
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Вывод ТОЛЬКО новых логов (без старых)
Get-Content -Path "{log_path}" -Wait -Tail 0 -Encoding UTF8
"""

    try:
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(ps_script_content)
    except Exception as e:
        logger.error(f"Не удалось создать PowerShell скрипт: {e}")
        return False

    # ===== ПОПЫТКА 1: Windows Terminal + PowerShell 7+ =====
    try:
        command = f'wt.exe pwsh -NoExit -ExecutionPolicy Bypass -File "{script_path}"'

        subprocess.Popen(command, shell=True)
        logger.success("Windows Terminal с PowerShell 7+ открыт")
        return True

    except FileNotFoundError:
        logger.debug("Windows Terminal не найден или PowerShell 7+ не установлен")
    except Exception as e:
        logger.debug(f"Не удалось запустить wt.exe + pwsh: {e}")

    # ===== ПОПЫТКА 2: Windows Terminal + PowerShell 5 =====
    try:
        command = f'wt.exe powershell -NoExit -ExecutionPolicy Bypass -File "{script_path}"'

        subprocess.Popen(command, shell=True)
        logger.success("Windows Terminal с PowerShell 5 открыт")
        logger.warning("Используется PowerShell 5 (установите PowerShell 7+ для лучшей производительности)")
        return True

    except FileNotFoundError:
        logger.debug("Windows Terminal не найден")
    except Exception as e:
        logger.debug(f"Не удалось запустить wt.exe + powershell: {e}")

    # ===== ПОПЫТКА 3: PowerShell 7+ отдельное окно =====
    try:
        command = f'start pwsh -NoExit -ExecutionPolicy Bypass -File "{script_path}"'

        subprocess.Popen(command, shell=True)
        logger.success("PowerShell 7+ открыт (отдельное окно)")
        return True

    except FileNotFoundError:
        logger.debug("PowerShell 7+ (pwsh) не установлен")
    except Exception as e:
        logger.debug(f"Не удалось запустить pwsh: {e}")

    # ===== ПОПЫТКА 4: PowerShell 5 отдельное окно (fallback) =====
    try:
        command = f'start powershell -NoExit -ExecutionPolicy Bypass -File "{script_path}"'

        subprocess.Popen(command, shell=True)
        logger.success("PowerShell 5 открыт (отдельное окно)")
        logger.warning("Используется PowerShell 5 (установите PowerShell 7+ и Windows Terminal для лучшей производительности)")
        return True

    except Exception as e:
        logger.error(f"Не удалось открыть терминал с логами (все попытки провалились): {e}")
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