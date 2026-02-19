"""
Выполнение игровых функций

ОБНОВЛЕНО: Изоляция ошибок каждой функции + заморозка при критических ошибках
"""

import time
import traceback
from utils.logger import logger
from utils.function_freeze_manager import function_freeze_manager

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
from functions.feeding_zone.feeding_zone import FeedingZoneFunction


# Порядок выполнения функций (из ТЗ)
FUNCTION_ORDER = [
    'mail_rewards',    # 1. Награды с почты (быстро, раз в день)
    'tiles',           # 2. Сбор с плиток (быстро, несколько раз в день)
    'shield',          # 3. Проверка щита (раз в 6 часов)
    'ponds',           # 4. Пополнение прудов (быстро, каждые 2.5-8ч)
    'feeding_zone',    # 5. Пополнение зоны кормления
    'building',        # 6. Строительство (основное, постоянно)
    'research',        # 7. Исследования (основное, постоянно)
    'wilds',           # 8. Дикие (если есть энергия)
    'coop',            # 9. Кооперации (если есть события)
    'prime_times',     # 10. Прайм таймы (специальные действия в определенное время)
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
    'feeding_zone': FeedingZoneFunction,
}


def execute_functions(emulator, active_functions):
    """
    Выполняет активные функции по порядку

    ОБНОВЛЕНО:
    - Каждая функция изолирована в try/except
    - При ошибке функция замораживается на 4 часа
    - Выполнение ПРОДОЛЖАЕТСЯ к следующим функциям
    - Функция НИКОГДА не бросает исключение наружу

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
    emulator_id = emulator.get('id')

    if not active_functions:
        logger.warning(
            f"[{emulator_name}] Нет активных функций для выполнения"
        )
        return

    # Фильтруем порядок только активными функциями
    ordered_active = [f for f in FUNCTION_ORDER if f in active_functions]

    if not ordered_active:
        logger.warning(
            f"[{emulator_name}] Активные функции не найдены "
            f"в FUNCTION_ORDER: {active_functions}"
        )
        return

    logger.info(f"[{emulator_name}] Порядок выполнения: {ordered_active}")

    # Счётчики для итогового лога
    executed = 0
    skipped_frozen = 0
    failed = 0

    for function_name in ordered_active:
        try:
            # === ПРОВЕРКА ЗАМОРОЗКИ ===
            if function_freeze_manager.is_frozen(emulator_id, function_name):
                unfreeze_at = function_freeze_manager.get_unfreeze_time(
                    emulator_id, function_name
                )
                time_str = (
                    unfreeze_at.strftime('%H:%M:%S') if unfreeze_at
                    else '?'
                )
                logger.warning(
                    f"[{emulator_name}] 🧊 Функция {function_name} "
                    f"заморожена до {time_str}, пропускаю"
                )
                skipped_frozen += 1
                continue

            # Получить класс функции
            function_class = FUNCTION_CLASSES.get(function_name)
            if not function_class:
                logger.error(
                    f"[{emulator_name}] Функция {function_name} "
                    f"не найдена в FUNCTION_CLASSES"
                )
                continue

            # Создать экземпляр и запустить
            function = function_class(emulator)
            function.run()
            executed += 1

        except Exception as e:
            # === КРИТИЧЕСКАЯ ОШИБКА В ФУНКЦИИ ===
            failed += 1
            tb = traceback.format_exc()

            logger.error(
                f"[{emulator_name}] ❌ КРИТИЧЕСКАЯ ОШИБКА "
                f"в функции {function_name}: {e}"
            )
            logger.error(f"[{emulator_name}] Traceback:\n{tb}")

            # Заморозить функцию на 4 часа
            function_freeze_manager.freeze(
                emulator_id=emulator_id,
                function_name=function_name,
                hours=4,
                reason=str(e)
            )

            # ПРОДОЛЖАЕМ к следующей функции!
            logger.info(
                f"[{emulator_name}] ➡️ Продолжаю к следующей функции..."
            )

        # Пауза между функциями
        time.sleep(1)

    # Итоговый лог
    logger.info(
        f"[{emulator_name}] 📊 Итого: выполнено={executed}, "
        f"заморожено={skipped_frozen}, ошибок={failed}"
    )