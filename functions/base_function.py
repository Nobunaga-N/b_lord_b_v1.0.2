"""
Базовый класс для всех игровых функций
"""

from utils.logger import logger


class BaseFunction:
    """
    Базовый класс для всех игровых функций

    Каждая функция должна:
    1. Проверять можно ли выполнять сейчас (can_execute)
    2. Выполнять свою логику (execute)
    3. Логировать результаты
    """

    def __init__(self, emulator):
        """
        Инициализация функции

        Args:
            emulator: словарь с данными эмулятора (id, name, port)
        """
        self.emulator = emulator
        self.emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        self.name = "BaseFunction"

    def can_execute(self):
        """
        Проверяет можно ли выполнять функцию сейчас

        Примеры проверок:
        - Щит: проверить когда последний раз проверяли (раз в 6 часов)
        - Строительство: всегда True на ЭТАПЕ 0
        - Прайм таймы: проверить текущее время

        Переопределяется в дочерних классах

        Returns:
            bool: True если функцию можно выполнять сейчас
        """
        return True

    def execute(self):
        """
        Основная логика выполнения функции

        Переопределяется в дочерних классах

        Raises:
            NotImplementedError: Если метод не переопределён в дочернем классе
        """
        raise NotImplementedError(f"{self.name}.execute() не реализован")

    def run(self):
        """
        Обертка для выполнения с логированием

        Вызывается из function_executor

        Returns:
            bool: True если функция выполнена успешно, False если пропущена или ошибка
        """
        # Проверка можно ли выполнять
        if not self.can_execute():
            logger.debug(f"[{self.emulator_name}] Функция {self.name} пропущена (не готова)")
            return False

        # Выполнение функции
        logger.info(f"[{self.emulator_name}] Выполнение: {self.name}")

        try:
            self.execute()
            logger.success(f"[{self.emulator_name}] Функция {self.name} завершена")
            return True

        except NotImplementedError:
            # Если метод не реализован - это нормально на ЭТАПЕ 0
            logger.debug(f"[{self.emulator_name}] Функция {self.name} ещё не реализована (заглушка)")
            return True

        except Exception as e:
            logger.error(f"[{self.emulator_name}] Ошибка в {self.name}: {e}")
            logger.exception(e)
            return False