"""
Функция: Строительство
"""

from functions.base_function import BaseFunction


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
        print(f"[DEBUG] [{self.emulator_name}] TODO: Логика строительства (ЭТАП 1)")
        pass