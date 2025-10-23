"""
Настройка логирования через loguru
С интеграцией журнала критических ошибок
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
    - CRITICAL: красный
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

    # === НОВОЕ: Обработчик для журнала критических ошибок ===
    logger.add(
        _error_log_sink,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="ERROR",  # Ловим ERROR и CRITICAL
        colorize=False,
        backtrace=True,
        diagnose=True,
    )

    logger.info("Логирование настроено")
    logger.debug(f"Файл логов: data/logs/bot.log")


def _error_log_sink(message):
    """
    Кастомный sink для перехвата ERROR и CRITICAL логов
    Отправляет их в ErrorLogManager

    Args:
        message: объект Record из loguru
    """
    try:
        # Импортируем здесь чтобы избежать циклических импортов
        from utils.error_log_manager import error_log_manager

        record = message.record

        # Извлекаем данные
        level = record["level"].name
        text = record["message"]
        formatted_line = f"[{record['time'].strftime('%H:%M:%S')}] {level: <8} | {text}"

        # Добавляем в журнал ошибок
        error_log_manager.add_error(
            log_line=formatted_line,
            level=level,
            message=text
        )

    except Exception:
        # Игнорируем ошибки в обработчике чтобы не сломать логирование
        pass


def _log_line_sink(message):
    """
    Кастомный sink для сбора всех строк лога (для контекста)

    Args:
        message: объект Record из loguru
    """
    try:
        from utils.error_log_manager import error_log_manager

        record = message.record
        formatted_line = f"[{record['time'].strftime('%H:%M:%S')}] {record['level'].name: <8} | {record['message']}"

        # Добавляем строку в буфер контекста
        error_log_manager.add_log_line(formatted_line)

    except Exception:
        pass


# Дополнительно добавляем sink для сбора всех строк (для контекста)
def add_context_collector():
    """Добавить коллектор контекста после основной настройки"""
    logger.add(
        _log_line_sink,
        format="{message}",
        level="DEBUG",
        colorize=False,
    )


def open_log_terminal():
    """
    Открывает Windows Terminal с логами в режиме tail -f

    ОБНОВЛЕНО: Создаёт улучшенную версию tail_logs.ps1 с обработкой ротации

    Приоритет:
    1. Windows Terminal + PowerShell 7+ (pwsh)
    2. Windows Terminal + PowerShell 5 (powershell)
    3. PowerShell 7+ отдельное окно (pwsh)
    4. PowerShell 5 отдельное окно (fallback)
    """

    # Путь к PowerShell скрипту
    script_path = os.path.abspath("data/logs/tail_logs.ps1")

    # Создаем PowerShell скрипт если его нет
    if not os.path.exists(script_path):
        logger.info("Создание PowerShell скрипта для логов...")
        os.makedirs(os.path.dirname(script_path), exist_ok=True)

        # ✅ УЛУЧШЕННАЯ ВЕРСИЯ с обработкой ротации
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write("""# Улучшенный скрипт для отслеживания логов с обработкой ротации
# Автоматически переподключается к новому файлу при ротации

$logPath = "bot.log"

Write-Host "==================================" -ForegroundColor Cyan
Write-Host "Beast Lord Bot - Логи" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "💡 Скрипт автоматически переподключится при ротации логов" -ForegroundColor Yellow
Write-Host "⚠️  Нажмите Ctrl+C для остановки" -ForegroundColor Gray
Write-Host ""

# Функция для безопасного чтения логов с обработкой ошибок
function Start-LogTail {
    param([string]$Path)

    $lastPosition = 0
    $reconnectAttempts = 0
    $maxReconnectAttempts = 3

    while ($true) {
        try {
            # Проверяем существование файла
            if (-not (Test-Path $Path)) {
                Write-Host "⏳ Ожидание создания файла логов..." -ForegroundColor Yellow
                Start-Sleep -Seconds 2
                continue
            }

            # Получаем информацию о файле
            $fileInfo = Get-Item $Path
            $currentSize = $fileInfo.Length

            # Если файл меньше последней позиции - произошла ротация
            if ($currentSize -lt $lastPosition) {
                Write-Host ""
                Write-Host "🔄 [$(Get-Date -Format 'HH:mm:ss')] Обнаружена ротация логов, переподключение..." -ForegroundColor Magenta
                Write-Host ""
                $lastPosition = 0
                $reconnectAttempts = 0
            }

            # Читаем новые строки
            if ($currentSize -gt $lastPosition) {
                $content = Get-Content -Path $Path -Encoding UTF8 -ErrorAction Stop

                # Выводим только новые строки
                $newLines = $content | Select-Object -Skip ([Math]::Max(0, $lastPosition))
                foreach ($line in $newLines) {
                    Write-Host $line
                }

                $lastPosition = $content.Count
                $reconnectAttempts = 0
            }

            # Небольшая пауза перед следующей проверкой
            Start-Sleep -Milliseconds 500

        }
        catch [System.IO.FileNotFoundException] {
            # Файл был удален/переименован - ротация
            Write-Host ""
            Write-Host "🔄 [$(Get-Date -Format 'HH:mm:ss')] Файл логов переименован (ротация), переподключение..." -ForegroundColor Magenta
            Write-Host ""

            $lastPosition = 0
            $reconnectAttempts++

            if ($reconnectAttempts -gt $maxReconnectAttempts) {
                Write-Host "❌ Превышено количество попыток переподключения" -ForegroundColor Red
                break
            }

            Start-Sleep -Seconds 2
        }
        catch {
            Write-Host "⚠️  Ошибка чтения логов: $($_.Exception.Message)" -ForegroundColor Red
            $reconnectAttempts++

            if ($reconnectAttempts -gt $maxReconnectAttempts) {
                Write-Host "❌ Превышено количество попыток переподключения" -ForegroundColor Red
                break
            }

            Start-Sleep -Seconds 2
        }
    }
}

# Запускаем слежение
try {
    Start-LogTail -Path $logPath
}
catch {
    Write-Host "❌ Критическая ошибка: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Нажмите Enter для выхода"
    exit 1
}
""")

    # ===== ПОПЫТКА 1: Windows Terminal + PowerShell 7+ =====
    try:
        # Проверяем наличие Windows Terminal
        wt_path = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe")

        if os.path.exists(wt_path):
            # Пробуем с pwsh
            command = f'start wt.exe -d data/logs pwsh -NoExit -ExecutionPolicy Bypass -File "{script_path}"'

            subprocess.Popen(command, shell=True)
            logger.success("Windows Terminal + PowerShell 7+ открыт")
            return True

    except FileNotFoundError:
        logger.debug("Windows Terminal не найден")
    except Exception as e:
        logger.debug(f"Не удалось запустить wt.exe + pwsh: {e}")

    # ===== ПОПЫТКА 2: Windows Terminal + PowerShell 5 =====
    try:
        wt_path = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe")

        if os.path.exists(wt_path):
            command = f'start wt.exe -d data/logs powershell -NoExit -ExecutionPolicy Bypass -File "{script_path}"'

            subprocess.Popen(command, shell=True)
            logger.success("Windows Terminal + PowerShell 5 открыт")
            logger.warning("Установите PowerShell 7+ для лучшей производительности")
            return True

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
        logger.warning(
            "Используется PowerShell 5 (установите PowerShell 7+ и Windows Terminal для лучшей производительности)")
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
add_context_collector()