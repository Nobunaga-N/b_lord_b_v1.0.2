"""
Базовый класс для всех игровых функций
"""

class BaseFunction:
    """Базовый класс функции"""

    def __init__(self, emulator):
        self.emulator = emulator
        self.name = "BaseFunction"

    def can_execute(self):
        """Проверяет можно ли выполнять функцию сейчас"""
        return True

    def execute(self):
        """Основная логика выполнения"""
        raise NotImplementedError(f"{self.name}.execute() не реализован")

    def run(self):
        """Обертка для выполнения с логированием"""
        if not self.can_execute():
            return False

        try:
            self.execute()
            return True
        except Exception as e:
            print(f"Ошибка в {self.name}: {e}")
            return False
