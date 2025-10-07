"""
Управление эмуляторами
"""

from utils.ldconsole_manager import find_ldconsole, start_emulator as ldconsole_start, stop_emulator as ldconsole_stop
from utils.logger import logger


class EmulatorManager:
    """Запуск/остановка эмуляторов через ldconsole"""

    def __init__(self):
        """Инициализация менеджера эмуляторов"""
        self.ldconsole_path = find_ldconsole()

        if not self.ldconsole_path:
            logger.error("ldconsole.exe не найден! EmulatorManager не сможет управлять эмуляторами")

    def start_emulator(self, emulator_id):
        """
        Запускает эмулятор по ID

        Args:
            emulator_id: ID эмулятора (0, 1, 2, ...)

        Returns:
            bool: True если запуск успешен, False если ошибка
        """
        if not self.ldconsole_path:
            logger.error(f"Не могу запустить эмулятор id={emulator_id}: ldconsole.exe не найден")
            return False

        try:
            ldconsole_start(self.ldconsole_path, emulator_id)
            logger.info(f"Эмулятор id={emulator_id} запущен")
            return True

        except Exception as e:
            logger.error(f"Ошибка запуска эмулятора id={emulator_id}: {e}")
            return False

    def stop_emulator(self, emulator_id):
        """
        Останавливает эмулятор по ID

        Args:
            emulator_id: ID эмулятора (0, 1, 2, ...)

        Returns:
            bool: True если остановка успешна, False если ошибка
        """
        if not self.ldconsole_path:
            logger.error(f"Не могу остановить эмулятор id={emulator_id}: ldconsole.exe не найден")
            return False

        try:
            ldconsole_stop(self.ldconsole_path, emulator_id)
            logger.info(f"Эмулятор id={emulator_id} остановлен")
            return True

        except Exception as e:
            logger.error(f"Ошибка остановки эмулятора id={emulator_id}: {e}")
            return False