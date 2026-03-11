"""
Выполнение игровых функций

ОБНОВЛЕНО v2.0 (W.0):
- Добавлен session_state (передаётся между проходами)
- Мульти-pass цикл для поддержки автоохоты (Wilds)
- Обновлён FUNCTION_ORDER (building перед wilds)
- Обратная совместимость: без wilds — ровно 1 проход

Версия: 2.0
Дата обновления: 2025-03-10
"""

import time
import math
import traceback
from datetime import datetime, timedelta
from utils.config_manager import load_config
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


# Порядок выполнения функций
# ОБНОВЛЕНО: building и wilds в начале, tiles после диких (нужны отряды)
FUNCTION_ORDER = [
    'building',        # 1. Строительство (назначить строителей)
    'wilds',           # 2. Дикие (запустить автоохоту)
    'research',        # 3. Эволюция
    'ponds',           # 4. Пополнение прудов
    'feeding_zone',    # 5. Зона кормления
    'mail_rewards',    # 6. Награды с почты
    'shield',          # 7. Щит
    'tiles',           # 8. Плитки (после диких — отправить отряды)
    'coop',            # 9. Кооперации
    'prime_times',     # 10. Прайм таймы
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
    'ponds': PondsFunction,
    'feeding_zone': FeedingZoneFunction,
}

# Максимум проходов (защита от бесконечного цикла)
MAX_PASSES = 20

# Максимум времени ожидания между проходами (секунды)
MAX_SLEEP_BETWEEN_PASSES = 600  # 10 минут


def execute_functions(emulator, active_functions, session_state=None,
                      is_running_check=None):
    """
    Выполняет активные функции по порядку с поддержкой мульти-pass

    МУЛЬТИ-PASS ЛОГИКА:
    - Проход 1: все функции по порядку (обычный)
    - После прохода: проверка session_state['wilds']['hunt_active']
    - Если True → sleep до проверки → Проход 2 (все функции снова,
      can_execute сами фильтруют что нужно)
    - Если False → выход из цикла
    - Без включённых wilds → ровно 1 проход (обратная совместимость)

    Args:
        emulator: словарь с данными эмулятора (id, name, port)
        active_functions: список названий активных функций
        session_state: dict — общее состояние сессии (создаётся если None)
        is_running_check: callable → bool, проверка что бот ещё работает
                          (для graceful shutdown во время мульти-pass)
    """
    if session_state is None:
        session_state = {}

    emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
    emulator_id = emulator.get('id')

    if not active_functions:
        logger.warning(f"[{emulator_name}] Нет активных функций для выполнения")
        return

    # Фильтруем порядок только активными функциями
    ordered_active = [f for f in FUNCTION_ORDER if f in active_functions]

    if not ordered_active:
        logger.warning(
            f"[{emulator_name}] Активные функции не найдены "
            f"в FUNCTION_ORDER: {active_functions}"
        )
        return

    # ===== МУЛЬТИ-PASS ЦИКЛ =====
    pass_number = 0

    while pass_number < MAX_PASSES:
        pass_number += 1

        # Проверка graceful shutdown
        if is_running_check and not is_running_check():
            logger.info(f"[{emulator_name}] 🛑 Бот останавливается, прерываю мульти-pass")
            break

        if pass_number == 1:
            logger.info(f"[{emulator_name}] Порядок выполнения: {ordered_active}")
        else:
            logger.info(
                f"[{emulator_name}] 🔄 Мульти-pass #{pass_number} "
                f"(автоохота активна)"
            )

        # === Один проход по всем функциям ===
        _run_single_pass(
            emulator, emulator_name, emulator_id,
            ordered_active, session_state, pass_number
        )

        # === Проверка: нужен ли следующий проход? ===
        wilds_state = session_state.get('wilds', {})
        hunt_active = wilds_state.get('hunt_active', False)

        if not hunt_active:
            # Автоохота не активна (или wilds не включены) → выход
            if pass_number > 1:
                logger.info(
                    f"[{emulator_name}] ✅ Автоохота завершена, "
                    f"выход из мульти-pass (проходов: {pass_number})"
                )
            break

        # Автоохота активна → рассчитать время ожидания
        sleep_seconds = _calculate_sleep_time(wilds_state)

        logger.info(
            f"[{emulator_name}] ⏳ Автоохота активна, "
            f"следующая проверка через {sleep_seconds}с "
            f"(~{sleep_seconds // 60} мин)"
        )

        # Сон с возможностью прерывания
        _sleep_interruptible(sleep_seconds, is_running_check)

    else:
        # MAX_PASSES достигнут
        logger.warning(
            f"[{emulator_name}] ⚠️ Достигнут лимит проходов ({MAX_PASSES}), "
            f"принудительный выход из мульти-pass"
        )


def _run_single_pass(emulator, emulator_name, emulator_id,
                     ordered_active, session_state, pass_number):
    """
    Один проход по всем функциям

    Args:
        emulator: dict эмулятора
        emulator_name: имя для логов
        emulator_id: ID эмулятора
        ordered_active: отфильтрованный список функций
        session_state: общее состояние сессии
        pass_number: номер прохода (для логов)
    """
    executed = 0
    skipped_frozen = 0
    failed = 0

    for function_name in ordered_active:

        # Проверка паузы эмулятора
        if _is_emulator_paused(emulator_id):
            logger.info(
                f"[{emulator_name}] ⏸ Эмулятор на паузе, "
                f"прерываю выполнение"
            )
            break

        try:
            # Проверка заморозки
            if function_freeze_manager.is_frozen(emulator_id, function_name):
                unfreeze_at = function_freeze_manager.get_unfreeze_time(
                    emulator_id, function_name
                )
                time_str = (
                    unfreeze_at.strftime('%H:%M:%S') if unfreeze_at
                    else '?'
                )
                # Логируем заморозку только на первом проходе
                if pass_number == 1:
                    logger.warning(
                        f"[{emulator_name}] 🧊 {function_name} "
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

            # Создать экземпляр с session_state и запустить
            function_instance = function_class(emulator, session_state)
            function_instance.run()
            executed += 1

        except Exception as e:
            # Критическая ошибка в функции
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

            logger.info(
                f"[{emulator_name}] ➡️ Продолжаю к следующей функции..."
            )

        # Пауза между функциями
        time.sleep(1)

    # Итоговый лог
    logger.info(
        f"[{emulator_name}] 📊 Проход #{pass_number}: "
        f"выполнено={executed}, заморожено={skipped_frozen}, "
        f"ошибок={failed}"
    )



def _calculate_sleep_time(wilds_state):
    """
    Рассчитать время ожидания до следующей проверки автоохоты

    Использует next_check_at — время установленное в момент
    запуска/проверки охоты (а не после завершения всех функций).

    Логика:
    - Если есть next_check_at → спим до него
    - Если нет → fallback на estimated_finish с ограничением 10мин
    - Минимум 60 секунд

    Returns:
        int: секунды ожидания
    """
    now = datetime.now()

    # Приоритет: next_check_at (установлен в момент запуска/проверки охоты)
    next_check = wilds_state.get('next_check_at')
    if next_check is not None:
        remaining = (next_check - now).total_seconds()
        if remaining > 0:
            return max(int(remaining), 60)
        else:
            # Уже пора проверять
            return 60

    # Fallback: estimated_finish (старая логика)
    estimated_finish = wilds_state.get('estimated_finish')
    if estimated_finish is None:
        return MAX_SLEEP_BETWEEN_PASSES

    remaining = (estimated_finish - now).total_seconds()
    if remaining <= 0:
        return 60

    sleep = min(remaining, MAX_SLEEP_BETWEEN_PASSES)
    return max(int(sleep), 60)


def _sleep_interruptible(seconds, is_running_check=None):
    """
    Сон с возможностью прерывания через is_running_check

    Проверяет каждую секунду, не остановлен ли бот.

    Args:
        seconds: сколько спать
        is_running_check: callable → bool
    """
    for _ in range(int(seconds)):
        if is_running_check and not is_running_check():
            logger.info("🛑 Мульти-pass прерван (бот останавливается)")
            return
        time.sleep(1)


def _is_emulator_paused(emulator_id):
    """Проверяет на паузе ли эмулятор"""
    try:
        gui_config = load_config("configs/gui_config.yaml", silent=True)
        if not gui_config:
            return False
        emu_settings = gui_config.get("emulator_settings", {})
        settings = emu_settings.get(
            str(emulator_id),
            emu_settings.get(emulator_id, {})
        )
        return settings.get("paused", False)
    except Exception:
        return False