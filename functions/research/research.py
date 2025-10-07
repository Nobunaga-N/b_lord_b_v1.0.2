"""
Функция: Исследования
"""

from functions.base_function import BaseFunction
from utils.logger import logger


class ResearchFunction(BaseFunction):
    """Функция исследований"""

    def __init__(self, emulator):
        super().__init__(emulator)
        self.name = "ResearchFunction"

    def execute(self):
        """
        TODO: Реализация исследований (ЭТАП 2)

        На ЭТАПЕ 0 это заглушка
        """
        logger.debug(f"[{self.emulator_name}] TODO: Логика исследований (ЭТАП 2)")
        pass