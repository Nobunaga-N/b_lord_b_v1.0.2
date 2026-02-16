"""
Выполнение игровых функций
"""

import time
from utils.logger import logger

# Импорты классов функций
from functions.building.building import BuildingFunction
from functions.research.research import ResearchFunction
from functions.wilds.wilds import WildsFunction
from functions.coop.coop import CoopFunction
from functions.tiles.tiles import TilesFunction
from functions.prime_times.prime_times import PrimeTimesFunction
from functions.shield.shield import ShieldFunction
from functions.mail_rewards.mail_rewards import MailRewardsFunction
from functions.ponds.ponds import PondsFunction


# Порядок выполнения функций (из ТЗ)
FUNCTION_ORDER = [
    'mail_rewards',    # 1. Награды с почты (быстро, раз в день)
    'tiles',           # 2. Сбор с плиток (быстро, несколько раз в день)
    'shield',          # 3. Проверка щита (раз в 6 часов)
    'ponds',           # 4. Пополнение прудов (быстро, каждые 2.5-8ч)
    'building',        # 5. Строительство (основное, постоянно)
    'research',        # 6. Исследования (основное, постоянно)
    'wilds',           # 7. Дикие (если есть энергия)
    'coop',            # 8. Кооперации (если есть события)
    'prime_times',     # 9. Прайм таймы (специальные действия в определенное время)
]

# Маппинг имя → класс
FUNCTION_CLASSES = {
    'building': BuildingFunction,
    'research': ResearchFunction,
    'wilds': WildsFunction,
    'coop': CoopFunction,
    'tiles': TilesFunction,
    'prime_times': PrimeTimesFunction,
    'shield': ShieldFunction,
    'mail_rewards': MailRewardsFunction,
    'ponds': PondsFunction,               # ← ДОБАВИТЬ
}


def execute_functions(emulator, active_functions):
    """
    Выполняет активные функции по порядку

    Args:
        emulator: словарь с данными эмулятора (id, name, port)
        active_functions: список названий активных функций (из конфига)
                         например: ['building', 'research', 'shield']

    Логика:
    - Берем FUNCTION_ORDER как основу порядка
    - Фильтруем только активные функции
    - Выполняем по очереди
    - Каждая функция сама решает можно ли ее выполнять (can_execute)
    """

    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    # Проверка входных данных
    if not active_functions:
        logger.warning(f"[{emulator_name}] Нет активных функций для выполнения")
        return

    # Фильтруем порядок только активными функциями
    ordered_active = [f for f in FUNCTION_ORDER if f in active_functions]

    if not ordered_active:
        logger.warning(f"[{emulator_name}] Активные функции не найдены в FUNCTION_ORDER: {active_functions}")
        return

    logger.info(f"[{emulator_name}] Порядок выполнения: {ordered_active}")

    # Выполняем функции по порядку
    for function_name in ordered_active:
        # Получить класс функции
        function_class = FUNCTION_CLASSES.get(function_name)

        if not function_class:
            logger.error(f"[{emulator_name}] Функция {function_name} не найдена в FUNCTION_CLASSES")
            continue

        # Создать экземпляр функции
        function = function_class(emulator)

        # Запустить функцию (с логированием внутри)
        function.run()

        # Небольшая пауза между функциями
        time.sleep(1)

    logger.info(f"[{emulator_name}] Все функции выполнены")