"""
Функция: Строительство
"""

from functions.base_function import BaseFunction
from utils.logger import logger


class BuildingFunction(BaseFunction):
    """Функция строительства зданий"""

    def __init__(self, emulator):
        super().__init__(emulator)
        self.name = "BuildingFunction"

    def execute(self):
        """
        TODO: Реализация строительства (ЭТАП 1)

        На ЭТАПЕ 0 это заглушка
        """
        logger.debug(f"[{self.emulator_name}] TODO: Логика строительства (ЭТАП 1)")
        pass