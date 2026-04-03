"""
Функция: PrimeTimesFunction — оркестратор праймтаймов (точка входа B, fallback)

Последний в FUNCTION_ORDER. Добивает ДС если building/training/research
не закрыли, а также обрабатывает ситуации когда основные функции отключены,
но prime_times включён.

Двухуровневая структура:
  Точка A (основная): building/training/research вызывают модули напрямую
  Точка B (fallback): PrimeTimesFunction.execute() — этот файл

Переиспользуемые модули:
  - NavigationPanel          → навигация к зданию (building, training)
  - BuildingUpgrade          → открытие окна ускорений (building)
  - TrainingNavigation       → постановка зверей + парсинг (training)
  - EvolutionUpgrade         → навигация в эволюцию (evolution)
  - BackpackStorage          → инвентарь ускорений
  - ds_schedule              → расписание ДС
  - ds_navigator             → парсинг очков ДС
  - speedup_calculator       → расчёт плана
  - speedup_applier          → непосредственная трата
  - PrimeStorage             → прогресс ДС

session_state['prime_times']:
  {
      'event_type': str,
      'points_per_min': int,
      'event_end': datetime,
      'event_key': str,
      'ds_parsed': bool,
      'current_points': int,
      'shell_1_points': int,
      'shell_2_points': int,
      'target_minutes': int,
      'target_shell': int,
      'spent_minutes': float,
      'drain_type': str,
      'completed': bool,
      'skip_reason': str | None,
  }

Контракт execute():
  return True  = ситуация обработана (ДС неактивен, пропуск, завершён, ошибка навигации → заморозка)
  return False = критическая ошибка → автозаморозка через run()

Версия: 1.0
"""

import time
import math
from datetime import datetime, timedelta
from typing import Optional, Dict

from functions.base_function import BaseFunction
from functions.prime_times.ds_schedule import (
    get_current_event, get_next_event, is_safe_to_start,
)
from functions.prime_times.ds_navigator import parse_ds_points
from functions.prime_times.speedup_calculator import (
    calculate_plan, choose_drain_type, calculate_target_minutes,
    THRESHOLD_HOURS, MAX_TARGET_HOURS,
)
from functions.prime_times.speedup_applier import drain_speedups
from functions.prime_times.prime_storage import PrimeStorage
from functions.backpack_speedups.backpack_storage import BackpackStorage

from utils.function_freeze_manager import function_freeze_manager
from utils.adb_controller import press_key
from utils.logger import logger

from gui.prime_times_settings_window import load_allowed_drain_types


# ═══════════════════════════════════════════════════
# КОНСТАНТЫ
# ═══════════════════════════════════════════════════

FUNCTION_NAME = 'prime_times'

# Заморозка при ошибке навигации (часы)
FREEZE_HOURS_NAV_ERROR = 1

# Минимум минут до конца ДС для старта
MIN_MINUTES_TO_START = 5

# Пауза между циклами drain
DELAY_BETWEEN_DRAINS = 1.0


class PrimeTimesFunction(BaseFunction):
    """
    Оркестратор праймтаймов (fallback, точка входа B)

    execute() инициализирует session_state, выбирает drain_type,
    навигирует к нужному зданию/тренировке/эволюции и сливает ускорения.
    """

    FUNCTION_NAME = 'prime_times'

    def __init__(self, emulator, session_state=None):
        super().__init__(emulator, session_state)
        self.name = "PrimeTimesFunction"

        # Ленивая инициализация
        self._panel = None
        self._building_upgrade = None
        self._training_nav = None
        self._evolution_upgrade = None
        self._prime_storage = None
        self._backpack_storage = None
        self._building_db = None
        self._training_db = None
        self._evolution_db = None

    # ==================== ЛЕНИВЫЕ СВОЙСТВА ====================

    @property
    def panel(self):
        if self._panel is None:
            from functions.building.navigation_panel import NavigationPanel
            self._panel = NavigationPanel()
        return self._panel

    @property
    def building_upgrade(self):
        if self._building_upgrade is None:
            from functions.building.building_upgrade import BuildingUpgrade
            self._building_upgrade = BuildingUpgrade()
        return self._building_upgrade

    @property
    def training_nav(self):
        if self._training_nav is None:
            from functions.training.training_navigation import TrainingNavigation
            self._training_nav = TrainingNavigation()
        return self._training_nav

    @property
    def evolution_upgrade(self):
        if self._evolution_upgrade is None:
            from functions.research.evolution_upgrade import EvolutionUpgrade
            self._evolution_upgrade = EvolutionUpgrade()
        return self._evolution_upgrade

    @property
    def prime_storage(self) -> PrimeStorage:
        if self._prime_storage is None:
            self._prime_storage = PrimeStorage()
        return self._prime_storage

    @property
    def backpack_storage(self) -> BackpackStorage:
        if self._backpack_storage is None:
            self._backpack_storage = BackpackStorage()
        return self._backpack_storage

    @property
    def building_db(self):
        if self._building_db is None:
            from functions.building.building_database import BuildingDatabase
            self._building_db = BuildingDatabase()
        return self._building_db

    @property
    def training_db(self):
        if self._training_db is None:
            from functions.training.training_database import TrainingDatabase
            self._training_db = TrainingDatabase()
        return self._training_db

    @property
    def evolution_db(self):
        if self._evolution_db is None:
            from functions.research.evolution_database import EvolutionDatabase
            self._evolution_db = EvolutionDatabase()
        return self._evolution_db

    # ==================== ПЛАНИРОВЩИК ====================

    @staticmethod
    def get_next_event_time(emulator_id: int) -> Optional[datetime]:
        """
        Когда prime_times потребует эмулятор?

        Лёгкая проверка через БД без запуска эмулятора.

        Логика:
        1. Заморожена → время разморозки
        2. Нет данных в speedup_inventory → datetime.min (парсить первым делом)
        3. Текущий ДС уже завершён → ищем следующий
        4. Ближайший ДС → проверяем хватает ли ≥30ч
        5. Не хватает → None

        Returns:
            datetime — когда нужен эмулятор
            None — эмулятор не нужен
        """
        # 1. Заморожена?
        if function_freeze_manager.is_frozen(emulator_id, FUNCTION_NAME):
            unfreeze_at = function_freeze_manager.get_unfreeze_time(
                emulator_id, FUNCTION_NAME
            )
            if unfreeze_at:
                return unfreeze_at
            return None

        storage = BackpackStorage()

        # 2. Рюкзак не парсился → парсить первым делом
        if not storage.has_data(emulator_id):
            return datetime.min

        # 3. Ближайший ДС
        now = datetime.now()
        event = get_current_event(now)
        next_evt = get_next_event(now) if event is None else None

        target_event = event or next_evt
        if target_event is None:
            return None

        event_key = target_event['event_key']

        # Уже завершён?
        prime_st = PrimeStorage()
        if prime_st.is_completed(emulator_id, event_key):
            # Ищем следующий после текущего
            if event is not None:
                next_evt = get_next_event(now)
            else:
                # next_evt уже найден, но проверим и его
                pass

            if next_evt is None:
                return None

            next_key = next_evt['event_key']
            if prime_st.is_completed(emulator_id, next_key):
                return None

            target_event = next_evt

        # 4. Хватает ли ускорений?
        inventory = storage.get_inventory(emulator_id)
        if not inventory:
            return None

        event_type = target_event['type']

        # Проверяем есть ли здания для строительства
        # (влияет на universal для training)
        has_buildings = True
        try:
            from functions.building.building_database import BuildingDatabase
            bdb = BuildingDatabase()
            has_buildings = bdb.has_buildings_to_upgrade(emulator_id)
        except Exception:
            pass

        from gui.prime_times_settings_window import load_allowed_drain_types
        allowed = load_allowed_drain_types(emulator_id)
        drain_type, total_hours = choose_drain_type(
            inventory, event_type, has_buildings,
            allowed_drain_types=allowed,
        )

        if drain_type is None:
            return None

        # 5. Возвращаем время начала
        return target_event['start']

    # ==================== can_execute ====================

    def can_execute(self) -> bool:
        """
        Можно ли выполнять prime_times сейчас?

        1. Заморожена → False
        2. Нет активного ДС → False
        3. ДС уже завершён → False
        4. До конца ДС < 5 мин И ещё не начинали → False
        5. Уже начали (spent > 0) → True (дорабатывать)
        6. Иначе → True
        """
        emu_id = self.emulator.get('id')

        # 1. Заморожена?
        if function_freeze_manager.is_frozen(emu_id, self.FUNCTION_NAME):
            return False

        # 2. Активный ДС?
        now = datetime.now()
        event = get_current_event(now)
        if event is None:
            return False

        event_key = event['event_key']

        # 3. Уже завершён в session_state?
        ds = self.session_state.get('prime_times')
        if ds and ds.get('completed'):
            if ds.get('event_key') == event_key:
                return False

        # Уже завершён в БД?
        if self.prime_storage.is_completed(emu_id, event_key):
            return False

        # 4/5. Проверяем время
        progress = self.prime_storage.get_progress(emu_id, event_key)
        spent = progress['spent_minutes'] if progress else 0

        if spent > 0:
            # Уже начали — дорабатываем
            return True

        # Ещё не начинали — проверяем время
        if not is_safe_to_start(now, MIN_MINUTES_TO_START):
            return False

        return True

    # ==================== execute ====================

    def execute(self) -> bool:
        """
        Fallback: добивает ДС если building/training/research не закрыли.

        1. Проверить/инициализировать session_state['prime_times']
        2. Если completed/skip → return True
        3. Навигация к нужной функции
        4. Цикл drain
        5. Обновить прогресс

        Returns:
            True  = обработано (включая пропуски, заморозки)
            False = критическая ошибка
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        now = datetime.now()
        event = get_current_event(now)

        if event is None:
            logger.debug(f"[{emu_name}] ДС неактивен")
            return True

        event_key = event['event_key']

        # ── Инициализация session_state ──
        ds = self.session_state.get('prime_times')

        if ds is None or ds.get('event_key') != event_key:
            ds = self._init_ds_session(event)
            if ds is None:
                return True  # Ошибка навигации → заморозка уже выставлена

        # ── Проверка статуса ──
        if ds.get('completed'):
            logger.debug(f"[{emu_name}] ДС {event_key} уже завершён")
            return True

        if ds.get('skip_reason'):
            logger.info(
                f"[{emu_name}] ДС {event_key} пропущен: "
                f"{ds['skip_reason']}"
            )
            return True

        # ── Цикл drain ──
        drain_type = ds['drain_type']

        logger.info(
            f"[{emu_name}] 🎯 ДС {event_key}: drain={drain_type}, "
            f"target={ds['target_minutes']} мин, "
            f"spent={ds['spent_minutes']:.0f} мин"
        )

        if drain_type == 'building':
            success = self._drain_building(ds, event)
        elif drain_type == 'training':
            success = self._drain_training(ds, event)
        elif drain_type == 'evolution':
            success = self._drain_evolution(ds, event)
        else:
            logger.error(f"[{emu_name}] Неизвестный drain_type: {drain_type}")
            return True

        return success

    # ==================== ИНИЦИАЛИЗАЦИЯ ДС ====================

    def _init_ds_session(self, event: Dict) -> Optional[Dict]:
        """
        Инициализировать session_state['prime_times'].

        1. Проверяем рюкзак
        2. Выбираем drain_type
        3. Парсим очки ДС
        4. Считаем target_minutes (или восстанавливаем из ds_progress)
        5. Формируем session_state

        FIX: Если ds_progress уже есть — используем сохранённый
        target_minutes, а не пересчитываем из текущих очков.
        Иначе current_points уже включает spent_minutes → двойной учёт.

        Returns:
            Dict (session_state['prime_times']) или None при ошибке
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name
        event_key = event['event_key']
        event_type = event['type']
        ppm = event['points_per_min']

        logger.info(
            f"[{emu_name}] 🔧 Инициализация ДС {event_key}: "
            f"type={event_type}, ppm={ppm}"
        )

        # ── 1. Инвентарь ──
        inventory = self.backpack_storage.get_inventory(emu_id)
        if not inventory:
            logger.warning(
                f"[{emu_name}] ⚠️ Нет данных об ускорениях, "
                f"пропускаем ДС"
            )
            self._set_skip(event_key, 'no_inventory')
            return self.session_state['prime_times']

        # ── 2. Есть ли здания для строительства ──
        has_buildings = self._check_has_buildings(emu_id)

        # ── 3. Выбор drain_type ──
        allowed = load_allowed_drain_types(emu_id)
        drain_type, total_hours = choose_drain_type(
            inventory, event_type, has_buildings,
            allowed_drain_types=allowed,
        )

        if drain_type is None:
            logger.info(
                f"[{emu_name}] ⏭️ Не хватает ускорений "
                f"(< {THRESHOLD_HOURS}ч)"
            )
            self._set_skip(event_key, 'not_enough_speedups')
            return self.session_state['prime_times']

        # ── 4. Проверяем ds_progress (ДО парсинга очков!) ──
        progress = self.prime_storage.get_progress(emu_id, event_key)

        if progress and progress['status'] == 'in_progress':
            # ═══ ВОССТАНОВЛЕНИЕ: target уже рассчитан при первом запуске ═══
            target_min = int(progress['target_minutes'])
            spent = float(progress['spent_minutes'])
            target_shell = int(progress.get('target_shell', 2))

            logger.info(
                f"[{emu_name}] 🔄 Восстановлено из ds_progress: "
                f"{spent:.0f}/{target_min} мин (shell {target_shell})"
            )

            # Парсим очки для session_state (информационно),
            # но НЕ пересчитываем target
            ds_points = parse_ds_points(self.emulator)
            if ds_points is None:
                # Не критично при восстановлении — данные есть в БД
                logger.warning(
                    f"[{emu_name}] ⚠️ Не удалось спарсить очки ДС "
                    f"при восстановлении, используем saved progress"
                )
                ds_points = {
                    'current': 0,
                    'shell_1': 0,
                    'shell_2': 0,
                }
        else:
            # ═══ ПЕРВЫЙ ЗАПУСК: парсим очки и считаем target ═══
            ds_points = parse_ds_points(self.emulator)

            if ds_points is None:
                logger.warning(
                    f"[{emu_name}] ⚠️ Не удалось спарсить очки ДС, "
                    f"замораживаем на {FREEZE_HOURS_NAV_ERROR}ч"
                )
                function_freeze_manager.freeze(
                    emu_id, self.FUNCTION_NAME,
                    hours=FREEZE_HOURS_NAV_ERROR,
                    reason="Ошибка парсинга очков ДС",
                )
                return None

            # ── 5. Рассчитать target_minutes ──
            target_shell = 2
            target_min = calculate_target_minutes(
                ds_points['current'], ds_points['shell_2'], ppm
            )

            # Лимит 65ч
            if target_min > MAX_TARGET_HOURS * 60:
                target_min_1 = calculate_target_minutes(
                    ds_points['current'], ds_points['shell_1'], ppm
                )
                if target_min_1 <= MAX_TARGET_HOURS * 60:
                    target_min = target_min_1
                    target_shell = 1
                    logger.info(
                        f"[{emu_name}] 2-я ракушка > "
                        f"{MAX_TARGET_HOURS}ч, "
                        f"целимся в 1-ю ({target_min} мин)"
                    )
                else:
                    self._set_skip(event_key, '>65h')
                    return self.session_state['prime_times']

            if target_min <= 0:
                logger.info(
                    f"[{emu_name}] ДС {event_key}: очки уже набраны"
                )
                self._set_completed(event_key)
                return self.session_state['prime_times']

            spent = 0.0

        # ── 6. Формируем session_state ──
        ds = {
            'event_type': event_type,
            'points_per_min': ppm,
            'event_end': event['end'],
            'event_key': event_key,
            'ds_parsed': True,
            'current_points': ds_points['current'],
            'shell_1_points': ds_points['shell_1'],
            'shell_2_points': ds_points['shell_2'],
            'target_minutes': target_min,
            'target_shell': target_shell,
            'spent_minutes': spent,
            'drain_type': drain_type,
            'completed': False,
            'skip_reason': None,
        }

        self.session_state['prime_times'] = ds

        self.prime_storage.save_progress(
            emu_id, event_key, target_min,
            int(spent), target_shell, 'in_progress',
        )

        logger.info(
            f"[{emu_name}] ✅ ДС инициализирован: drain={drain_type}, "
            f"target={target_min} мин (shell {target_shell}), "
            f"spent={spent:.0f} мин"
        )

        return ds

    # ==================== DRAIN: BUILDING ====================

    def _drain_building(self, ds: Dict, event: Dict) -> bool:
        """
        Цикл drain для строительства (fallback, точка B).

        1. Найти здание с таймером
        2. Если нет — поставить новое здание на улучшение
        3. Открыть окно ускорений
        4. drain_speedups()
        5. Обновить прогресс
        6. Если здание достроилось → следующее здание → continue
        7. Если набрали очки → break

        ✅ FIX #9: expected_level при навигации
        ✅ FIX #12: skip навигации когда speedup_open=True

        Returns:
            True = обработано
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        bp_storage = BackpackStorage()

        while ds['spent_minutes'] < ds['target_minutes']:
            # Проверяем время
            if not is_safe_to_start(min_minutes=MIN_MINUTES_TO_START):
                if ds['spent_minutes'] <= 0:
                    logger.info(
                        f"[{emu_name}] ⏱️ До конца ДС < "
                        f"{MIN_MINUTES_TO_START} мин, выходим"
                    )
                    break

            # ✅ FIX #10: Синхронизация БД с реальностью
            self.building_db.get_free_builder(emu_id)

            # ── Флаг: окно ускорений уже открыто? ──
            speedup_already_open = False

            # Найти здание с максимальным таймером
            building_info = self._find_building_with_timer(emu_id)

            # ── Нет зданий с таймером → поставить новое ──
            if building_info is None:
                logger.info(
                    f"[{emu_name}] ⚠️ Нет зданий с активным таймером, "
                    f"пробуем поставить новое..."
                )
                start_result = self._start_building_for_drain(emu_id)

                if start_result is None:
                    logger.warning(
                        f"[{emu_name}] ⚠️ Не удалось поставить здание, "
                        f"выходим из drain"
                    )
                    break

                # ✅ FIX #12: используем инфу из start_result
                building_info = start_result
                speedup_already_open = start_result.get(
                    'speedup_open', False
                )

            building_name = building_info['name']
            building_index = building_info.get('index')
            building_level = building_info.get('current_level')

            # ── Навигация + открытие окна ускорений ──
            # (пропускаем если окно уже открыто после _start_building_for_drain)
            if not speedup_already_open:
                # ✅ FIX #9: Навигация с expected_level
                nav_ok = self.panel.navigate_to_building(
                    self.emulator, building_name, building_index,
                    expected_level=building_level,
                )
                if not nav_ok:
                    logger.error(
                        f"[{emu_name}] ❌ Навигация к "
                        f"{building_name} провалилась"
                    )
                    self._reset_nav_state()
                    break

                # Клик по зданию → иконки действий
                from utils.adb_controller import tap as adb_tap
                adb_tap(self.emulator, x=268, y=517)
                time.sleep(1.5)

                # Открыть окно ускорений
                if not self.building_upgrade._open_speedup_window(
                    self.emulator
                ):
                    # ✅ FIX #8: continue вместо break
                    logger.warning(
                        f"[{emu_name}] ❌ Иконка ускорения не найдена, "
                        f"здание возможно уже завершено"
                    )
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    self._reset_nav_state()
                    continue

            # ── Рассчитать план НА ЭТО ЗДАНИЕ ──
            remaining_ds_min = int(
                ds['target_minutes'] - ds['spent_minutes']
            )
            building_timer_sec = building_info.get('timer_sec', 0)
            building_timer_min = max(1, math.ceil(building_timer_sec / 60))
            batch_target = min(remaining_ds_min, building_timer_min)

            logger.info(
                f"[{emu_name}] Prime пачка: "
                f"таймер здания={building_timer_min}мин, "
                f"осталось ДС={remaining_ds_min}мин, "
                f"batch={batch_target}мин"
            )

            inventory = bp_storage.get_inventory(emu_id)
            has_buildings = self.building_db.has_buildings_to_upgrade(emu_id)

            # ✅ FIX #3: Передаём timers
            timers = {'building_1': building_timer_sec}

            plan = calculate_plan(
                inventory=inventory,
                target_minutes=batch_target,
                event_type=ds['event_type'],
                drain_type='building',
                has_buildings=has_buildings,
                target_shell=ds['target_shell'],
                skip_threshold=True,
                timers=timers,
            )

            if plan.is_skip:
                logger.info(
                    f"[{emu_name}] План пустой: {plan.skip_reason}"
                )
                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                self._reset_nav_state()
                break

            # ── Drain ──
            result = drain_speedups(
                self.emulator, plan, 'building', self.session_state
            )

            # Обновить прогресс
            self._update_progress(ds, result.minutes_spent, event)

            self._reset_nav_state()

            if result.building_completed:
                logger.info(
                    f"[{emu_name}] 🏗️ Здание достроилось, "
                    f"обновляем БД..."
                )
                # ✅ FIX #2: Обновить здание + освободить строителя
                building = self.building_db.get_building(
                    emu_id, building_name, building_index
                )
                if building:
                    building_id = building['id']
                    new_level = (
                        building.get('upgrading_to_level')
                        or building['current_level'] + 1
                    )
                    self.building_db.update_building_level(
                        emu_id, building_name, building_index, new_level
                    )
                    with self.building_db.db_lock:
                        cursor = self.building_db.conn.cursor()
                        cursor.execute("""
                            UPDATE builders
                            SET is_busy = 0, building_id = NULL,
                                finish_time = NULL
                            WHERE emulator_id = ? AND building_id = ?
                        """, (emu_id, building_id))
                        self.building_db.conn.commit()

                # ✅ FIX #11: Пересчитать индексы
                if building_index is not None:
                    self.building_db.recalculate_building_indices(
                        emu_id, building_name
                    )

                time.sleep(DELAY_BETWEEN_DRAINS)
                continue  # → следующая итерация найдёт/поставит здание

            # Не достроилось → закрываем окно ускорений
            press_key(self.emulator, "ESC")
            time.sleep(0.5)
            break

        # Финализация
        self._finalize_ds(ds, event)
        return True

    def _start_building_for_drain(self, emu_id: int) -> Optional[dict]:
        """
        Поставить здание на улучшение для drain (fallback).

        Используется когда нет зданий с активным таймером.
        Аналог building.py._start_next_building(), но через
        ленивые свойства prime_times.

        ✅ FIX #4: Не ставить здания пока Лорд улучшается.
        ✅ FIX #12: keep_speedup_open=True — окно ускорений остаётся
           открытым, drain loop пропускает повторную навигацию.

        Returns:
            dict с полями:
                name, index, current_level, timer_sec, speedup_open
            или None при ошибке / нет зданий
        """
        lord = self.building_db.get_building(emu_id, "Лорд", None)
        if lord and lord['status'] == 'upgrading':
            logger.info(
                f"[{self.emulator_name}] Prime: Лорд улучшается, "
                f"строители простаивают"
            )
            return None

        free_builder = self.building_db.get_free_builder(emu_id)
        if free_builder is None:
            return None

        next_building = self.building_db.get_next_building_to_upgrade(
            self.emulator, auto_scan=False
        )
        if not next_building:
            return None

        b_name = next_building['name']
        b_index = next_building.get('index')
        action = next_building.get('action', 'upgrade')

        # Лорд не ставится через prime drain
        if next_building.get('is_lord'):
            return None

        if action == 'build':
            return None

        success = self.panel.navigate_to_building(
            self.emulator, b_name, building_index=b_index,
            expected_level=next_building['current_level'],
        )
        if not success:
            self._reset_nav_state()
            return None

        detected_level = self.panel.last_detected_level

        # ✅ FIX #12: keep_speedup_open=True — не закрываем окно ускорений
        upgrade_ok, timer_sec = self.building_upgrade.upgrade_building(
            self.emulator, building_name=b_name, building_index=b_index,
            keep_speedup_open=True,
        )

        self._reset_nav_state()

        if upgrade_ok and timer_sec and timer_sec > 0:
            timer_finish = datetime.now() + timedelta(seconds=timer_sec)
            self.building_db.set_building_upgrading(
                emu_id, b_name, b_index,
                timer_finish, free_builder,
                actual_level=detected_level,
            )
            display = b_name + (f" #{b_index}" if b_index else "")
            logger.success(
                f"[{self.emulator_name}] Prime: {display} "
                f"поставлено на улучшение"
            )
            return {
                'name': b_name,
                'index': b_index,
                'current_level': detected_level or next_building['current_level'],
                'timer_sec': timer_sec,
                'speedup_open': True,
            }

        elif upgrade_ok and (timer_sec == 0 or timer_sec is None):
            new_level = (
                (detected_level or next_building['current_level']) + 1
            )
            self.building_db.update_building_level(
                emu_id, b_name, b_index, new_level
            )
            # Мгновенное завершение — рекурсивно ставим следующее
            return self._start_building_for_drain(emu_id)

        return None


    # ==================== DRAIN: TRAINING ====================

    def _drain_training(self, ds: Dict, event: Dict) -> bool:
        """
        Цикл drain для тренировки (fallback, точка B).

        Архитектура: двойной цикл.
        - Внешний: навигация к зданию + открытие окна ускорений
        - Внутренний: drain по пачкам БЕЗ повторной навигации
          (парсим таймер → план → drain → если завершилось →
          "Обучение" → "Ускорение" → continue внутренний)

        Три сценария:
        1) Слот свободен → train_troops() → ESC → проваливаемся в (2)
        2) Слот занят → NavigationPanel → клик здание → "Обучение"
           → "Ускорение" → внутренний цикл
        3) Drain завершил тренировку → кнопка "Обучение" → ставим
           новых → "Ускорение" → continue внутренний (без навигации)

        Returns:
            True = обработано
        """
        import os
        from functions.prime_times.speedup_applier import _parse_remaining_timer
        from utils.ocr_engine import OCREngine
        ocr = OCREngine()

        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        building_type = 'carnivore'
        building_name = 'Логово Плотоядных'

        BASE_DIR = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        speedup_btn_path = os.path.join(
            BASE_DIR, 'data', 'templates', 'prime_times', 'button_speedup.png'
        )
        training_btn_path = os.path.join(
            BASE_DIR, 'data', 'templates', 'training', 'button_training.png'
        )

        # ════════════════════════════════════════════
        # ВНЕШНИЙ ЦИКЛ: навигация + запуск тренировки
        # ════════════════════════════════════════════
        while ds['spent_minutes'] < ds['target_minutes']:
            if not is_safe_to_start(min_minutes=MIN_MINUTES_TO_START):
                if ds['spent_minutes'] <= 0:
                    logger.info(f"[{emu_name}] ⏱️ Мало времени до конца ДС")
                break

            # ── ШАГ 1: Убедиться что тренировка активна ──
            self.training_db.clear_finished_slots(emu_id)
            slot_free = self.training_db.is_slot_free(emu_id, building_type)

            if slot_free:
                # ═══ СЦЕНАРИЙ 1: Слот свободен → поставить зверей ═══
                logger.info(f"[{emu_name}] Prime: слот свободен, ставим зверей")

                nav_ok = self.panel.navigate_to_building(
                    self.emulator, building_name
                )
                if not nav_ok:
                    logger.error(
                        f"[{emu_name}] ❌ Навигация к "
                        f"{building_name} провалилась"
                    )
                    self._reset_nav_state()
                    break

                tier = self.training_db.get_carnivore_tier(emu_id)
                status, timer_sec, _ = self.training_nav.train_troops(
                    self.emulator, building_type, tier
                )
                # train_troops() делает ESC → бот в поместье
                self._reset_nav_state()

                if status != 'started':
                    logger.warning(
                        f"[{emu_name}] Prime: train_troops → {status}"
                    )
                    break

                if timer_sec:
                    self.training_db.start_training(
                        emu_id, building_type, tier, timer_sec
                    )
                # Проваливаемся в шаг 2 ↓

            # ── ШАГ 2: Навигация к окну ускорений ──
            logger.info(
                f"[{emu_name}] Prime: открываем окно ускорений тренировки"
            )

            nav_ok = self.panel.navigate_to_building(
                self.emulator, building_name
            )
            if not nav_ok:
                logger.error(
                    f"[{emu_name}] ❌ Навигация к "
                    f"{building_name} провалилась"
                )
                self._reset_nav_state()
                break

            # Клик по зданию → иконки вокруг
            from utils.adb_controller import tap
            tap(self.emulator, 268, 517)
            time.sleep(1.5)

            # Иконка "Обучение" → окно тренировки с таймером
            if not self.training_nav._click_training_icon(self.emulator):
                logger.error(
                    f"[{emu_name}] ❌ Иконка 'Обучение' не найдена"
                )
                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                self._reset_nav_state()
                break

            # Кнопка "Ускорение" → окно с ускорениями
            if not self._click_template(speedup_btn_path, 'Ускорение'):
                logger.error(
                    f"[{emu_name}] ❌ Кнопка 'Ускорение' не найдена"
                )
                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                self._reset_nav_state()
                break

            time.sleep(1.0)

            # ════════════════════════════════════════
            # ШАГ 3: ВНУТРЕННИЙ ЦИКЛ — drain по пачкам
            # Бот в окне ускорений. Каждая итерация = 1 пачка.
            # ════════════════════════════════════════
            while ds['spent_minutes'] < ds['target_minutes']:
                # Проверка времени ДС
                # Если spent > 0 — бот уже в процессе, батч = секунды,
                # безопасно продолжать до конца ДС (ТЗ §15.4)
                if not is_safe_to_start(min_minutes=5):
                    if ds['spent_minutes'] <= 0:
                        logger.info(
                            f"[{emu_name}] Prime: мало времени "
                            f"до конца ДС, не начинаем"
                        )
                        press_key(self.emulator, "ESC")
                        time.sleep(0.5)
                        press_key(self.emulator, "ESC")
                        time.sleep(0.5)
                        break
                    # spent > 0: продолжаем, один батч занимает секунды
                    logger.debug(
                        f"[{emu_name}] Prime: <5 мин до конца ДС, "
                        f"но spent={ds['spent_minutes']:.0f}>0, "
                        f"добиваем"
                    )

                # ── Парсим таймер ТЕКУЩЕЙ пачки из окна ускорений ──
                batch_timer_sec = _parse_remaining_timer(
                    self.emulator, ocr, 'training'
                )

                if not batch_timer_sec or batch_timer_sec <= 0:
                    logger.warning(
                        f"[{emu_name}] Prime: не удалось спарсить "
                        f"таймер тренировки"
                    )
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                batch_timer_min = max(1, math.ceil(batch_timer_sec / 60))
                remaining_ds_min = int(
                    ds['target_minutes'] - ds['spent_minutes']
                )
                batch_target = min(remaining_ds_min, batch_timer_min)

                logger.info(
                    f"[{emu_name}] Prime пачка: тренировка, "
                    f"таймер={batch_timer_min}мин, "
                    f"осталось ДС={remaining_ds_min}мин, "
                    f"batch={batch_target}мин"
                )

                # ── План на ЭТУ ПАЧКУ ──
                inventory = self.backpack_storage.get_inventory(emu_id)
                has_buildings = self._check_has_buildings(emu_id)

                timers = {'training_carnivore': batch_timer_sec}

                plan = calculate_plan(
                    inventory=inventory,
                    target_minutes=batch_target,
                    event_type=ds['event_type'],
                    drain_type='training',
                    has_buildings=has_buildings,
                    target_shell=ds['target_shell'],
                    skip_threshold=True,
                    timers=timers,
                )

                if plan.is_skip:
                    logger.info(
                        f"[{emu_name}] План пустой: {plan.skip_reason}"
                    )
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                # ── Drain ──
                result = drain_speedups(
                    self.emulator, plan, 'training', self.session_state
                )

                self._update_progress(ds, result.minutes_spent, event)

                if not result.building_completed:
                    # Тренировка ещё идёт → план потрачен,
                    # закрываем окно ускорений + окно тренировки
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                # ═══ СЦЕНАРИЙ 3: Тренировка завершилась ═══
                # Окно ускорений закрылось → бот видит окно выбора зверей
                logger.info(f"[{emu_name}] 🎓 Тренировка завершилась!")
                self.training_db.clear_finished_slots(emu_id)

                # Проверяем: набрали ли очки ДС?
                if ds['spent_minutes'] >= ds['target_minutes']:
                    logger.info(
                        f"[{emu_name}] Prime: ДС цель достигнута"
                    )
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                # Кликаем "Обучение" → ставим новых зверей
                if not self._click_template(
                        training_btn_path, 'Обучение', delay_after=2.0
                ):
                    logger.warning(
                        f"[{emu_name}] Prime: кнопка 'Обучение' "
                        f"не найдена"
                    )
                    break

                logger.info(
                    f"[{emu_name}] Prime: новые звери поставлены"
                )

                # Парсим таймер новой пачки
                timer_sec = self.training_nav._parse_training_timer(
                    self.emulator
                )
                if timer_sec:
                    tier = self.training_db.get_carnivore_tier(emu_id)
                    self.training_db.start_training(
                        emu_id, building_type, tier, timer_sec
                    )

                # "Ускорение" → обратно в окно ускорений
                if not self._click_template(speedup_btn_path, 'Ускорение'):
                    logger.error(
                        f"[{emu_name}] Prime: кнопка 'Ускорение' "
                        f"не найдена"
                    )
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                time.sleep(1.0)
                # continue → внутренний цикл: следующая пачка

            # ── Внутренний цикл завершён ──
            # Повторная навигация не нужна: если break — значит
            # либо цель, либо ошибка, либо ДС кончился.
            self._reset_nav_state()
            break

        # ════════════════════════════════════════════
        # ФИНАЛИЗАЦИЯ
        # ════════════════════════════════════════════
        self._finalize_ds(ds, event)
        return True

    # ==================== DRAIN: EVOLUTION ====================

    def _drain_evolution(self, ds: Dict, event: Dict) -> bool:
        """
        Цикл drain для эволюции.

        1. EvolutionUpgrade → открыть окно эволюции → найти технологию
        2. Кнопка "Ускорение" → окно ускорений
        3. drain_speedups()
        4. Если эволюция завершилась → ESC → следующая технология → continue
        5. Если набрали очки → парсим таймер → ESC×3 → break

        Returns:
            True = обработано
        """
        from functions.prime_times.speedup_applier import _parse_remaining_timer
        from utils.ocr_engine import OCREngine
        ocr = OCREngine()
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        while ds['spent_minutes'] < ds['target_minutes']:
            if not is_safe_to_start(min_minutes=MIN_MINUTES_TO_START):
                if ds['spent_minutes'] <= 0:
                    break

            # Проверяем есть ли активная эволюция или ставим новую
            has_active = self.evolution_db.is_slot_busy(emu_id)

            if not has_active:
                # Нужно запустить новую эволюцию
                next_tech = self.evolution_db.get_next_tech_to_research(emu_id)
                if next_tech is None:
                    logger.info(f"[{emu_name}] Нет технологий для исследования")
                    break

                tech_name = next_tech['tech_name']
                section_name = next_tech['section_name']
                swipe_config = self.evolution_db.get_swipe_config(section_name)
                swipe_group = next_tech.get('swipe_group', 0)

                status, timer_sec = self.evolution_upgrade.research_tech(
                    self.emulator,
                    tech_name=tech_name,
                    section_name=section_name,
                    swipe_config=swipe_config,
                    swipe_group=swipe_group,
                )

                if status != 'started':
                    logger.warning(
                        f"[{emu_name}] Не удалось запустить эволюцию: "
                        f"{status}"
                    )
                    break

                if timer_sec:
                    self.evolution_db.start_research(
                        emu_id, tech_name, section_name, timer_sec
                    )

            # Бот в поместье после research_tech (ESC×3 внутри)
            # Открываем эволюцию снова для ускорения
            if not self.evolution_upgrade.open_evolution_window(self.emulator):
                logger.error(f"[{emu_name}] ❌ Не удалось открыть окно эволюции")
                break

            # Переходим к активной технологии (она подсвечена)
            # Находим раздел и кликаем по технологии
            active_tech = self._get_active_evolution(emu_id)
            if active_tech is None:
                logger.error(f"[{emu_name}] ❌ Нет активной эволюции в БД")
                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                break

            section_name = active_tech['section_name']
            tech_name = active_tech['tech_name']

            if not self.evolution_upgrade.navigate_to_section(
                self.emulator, section_name
            ):
                logger.error(f"[{emu_name}] ❌ Навигация к разделу {section_name}")
                self._close_evolution(3)
                break

            # Находим технологию и кликаем
            swipe_config = self.evolution_db.get_swipe_config(section_name)
            swipe_group = active_tech.get('swipe_group', 0)
            self.evolution_upgrade.perform_swipes(
                self.emulator, swipe_config, swipe_group
            )

            tech_coords = self.evolution_upgrade.find_tech_on_screen(
                self.emulator, tech_name
            )
            if tech_coords is None:
                logger.error(f"[{emu_name}] ❌ Технология {tech_name} не найдена")
                self._close_evolution(3)
                break

            from utils.adb_controller import tap
            tap(self.emulator, x=tech_coords[0], y=tech_coords[1])
            time.sleep(2.0)

            # Кнопка "Ускорение" внутри окна технологии
            import os as _os
            _BASE = _os.path.dirname(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            )
            _speedup_path = _os.path.join(
                _BASE, 'data', 'templates', 'prime_times', 'button_speedup.png'
            )
            if not self._click_template(_speedup_path, 'Ускорение'):
                logger.error(f"[{emu_name}] ❌ Кнопка 'Ускорение' не найдена в эволюции")
                self._close_evolution(4)
                break

            time.sleep(1.0)

            # ── Парсим таймер ТЕКУЩЕЙ эволюции из окна ускорений ──
            evo_timer_sec = _parse_remaining_timer(
                self.emulator, ocr, 'evolution'
            )

            if not evo_timer_sec or evo_timer_sec <= 0:
                logger.warning(
                    f"[{emu_name}] Prime: не удалось спарсить "
                    f"таймер эволюции"
                )
                self._close_evolution(4)
                break

            evo_timer_min = max(1, math.ceil(evo_timer_sec / 60))
            remaining_ds_min = int(ds['target_minutes'] - ds['spent_minutes'])
            batch_target = min(remaining_ds_min, evo_timer_min)

            logger.info(
                f"[{emu_name}] Prime пачка: эволюция, "
                f"таймер={evo_timer_min}мин, "
                f"осталось ДС={remaining_ds_min}мин, "
                f"batch={batch_target}мин"
            )

            # Рассчитать план (universal НИКОГДА для эволюции)
            inventory = self.backpack_storage.get_inventory(emu_id)

            #Передаём timers
            timers = {'evolution': evo_timer_sec}

            plan = calculate_plan(
                inventory=inventory,
                target_minutes=batch_target,
                event_type=ds['event_type'],
                drain_type='evolution',
                has_buildings=True,
                target_shell=ds['target_shell'],
                skip_threshold=True,
                timers=timers,  # ← FIX #10
            )

            if plan.is_skip:
                logger.info(f"[{emu_name}] План пустой: {plan.skip_reason}")
                self._close_evolution(4)
                break

            # Drain
            result = drain_speedups(
                self.emulator, plan, 'evolution', self.session_state
            )

            self._update_progress(ds, result.minutes_spent, event)

            if result.building_completed:
                logger.info(f"[{emu_name}] 🧬 Эволюция завершилась!")

                # ✅ FIX #5: Обновить БД (уровень технологии + освободить слот)
                # finish_time ещё в будущем, но ускорение завершило эволюцию
                self.evolution_db._complete_research(emu_id)

                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                self._close_evolution(2)
                time.sleep(DELAY_BETWEEN_DRAINS)
                continue

            # Не завершилась → закрываем всё
            self._close_evolution(4)
            break

        self._finalize_ds(ds, event)
        return True

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    def _check_has_buildings(self, emu_id: int) -> bool:
        """Есть ли здания для улучшения на эмуляторе?"""
        try:
            return self.building_db.has_buildings_to_upgrade(emu_id)
        except Exception:
            return True  # По умолчанию считаем что есть

    def _find_building_with_timer(self, emu_id: int) -> Optional[Dict]:
        """
        Найти здание с максимальным активным таймером.
        ✅ FIX #4: Исключает Лорда
        ✅ FIX #9: Возвращает current_level для navigate_to_building

        Возвращает {'name': str, 'index': int|None, 'timer_sec': int}
        или None если нет зданий с таймерами.
        """
        now = datetime.now()
        best = None
        best_remaining = 0

        try:
            with self.building_db.db_lock:
                cursor = self.building_db.conn.cursor()
                cursor.execute("""
                                SELECT b.building_name, b.building_index,
                                       b.current_level, br.finish_time
                                FROM builders br
                                JOIN buildings b ON br.building_id = b.id
                                WHERE br.emulator_id = ? AND br.is_busy = 1
                                      AND br.finish_time IS NOT NULL
                                      AND b.building_name != 'Лорд'
                            """, (emu_id,))

                for row in cursor.fetchall():
                    ft = row['finish_time']
                    if isinstance(ft, str):
                        ft = datetime.fromisoformat(ft)
                    remaining = (ft - now).total_seconds()
                    if remaining > best_remaining:
                        best_remaining = remaining
                        best = {
                            'name': row['building_name'],
                            'index': row['building_index'],
                            'timer_sec': int(remaining),
                            'current_level': row['current_level'],
                        }
        except Exception as e:
            logger.error(f"Ошибка _find_building_with_timer: {e}")

        return best

    def _get_active_evolution(self, emu_id: int) -> Optional[Dict]:
        """Получить активную (исследуемую) технологию из БД."""
        try:
            with self.evolution_db.db_lock:
                cursor = self.evolution_db.conn.cursor()
                cursor.execute("""
                    SELECT e.tech_name, e.section_name, e.swipe_group
                    FROM evolution_slot es
                    JOIN evolutions e ON es.tech_id = e.id
                    WHERE es.emulator_id = ? AND es.is_busy = 1
                """, (emu_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        'tech_name': row['tech_name'],
                        'section_name': row['section_name'],
                        'swipe_group': row['swipe_group'] if 'swipe_group' in row.keys() else 0,
                    }
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении активной эволюции: {e}")
            return None

    def _click_template(
        self, template_path: str, label: str,
        threshold: float = 0.85, delay_after: float = 0.0
    ) -> bool:
        """
        Найти шаблон на экране и кликнуть по нему.

        Args:
            template_path: полный путь к PNG шаблону
            label: название для логов (напр. "Ускорение")
            threshold: порог совпадения
            delay_after: пауза после клика (сек)

        Returns:
            True если найден и кликнут
        """
        import os
        from utils.image_recognition import find_image

        if not os.path.exists(template_path):
            logger.warning(f"⚠️ Шаблон {label} не найден: {template_path}")
            return False

        for attempt in range(3):
            result = find_image(
                self.emulator, template_path, threshold=threshold
            )
            if result:
                from utils.adb_controller import tap
                cx, cy = result
                tap(self.emulator, x=cx, y=cy)
                if delay_after > 0:
                    time.sleep(delay_after)
                logger.debug(
                    f"[{self.emulator_name}] ✅ Кнопка '{label}' "
                    f"нажата ({cx}, {cy})"
                )
                return True
            time.sleep(0.5)

        logger.warning(
            f"[{self.emulator_name}] ⚠️ Кнопка '{label}' не найдена"
        )
        return False

    def _close_evolution(self, esc_count: int):
        """Закрыть окна эволюции ESC × N."""
        for _ in range(esc_count):
            press_key(self.emulator, "ESC")
            time.sleep(0.5)

    def _reset_nav_state(self):
        """Сбросить состояние навигационной панели."""
        try:
            self.panel.nav_state.close_panel()
        except Exception:
            pass

    # ==================== ПРОГРЕСС И СТАТУС ====================

    def _update_progress(
        self, ds: Dict, minutes_spent: float, event: Dict
    ):
        """Обновить spent_minutes в session_state и ds_progress."""
        emu_id = self.emulator.get('id')
        event_key = event['event_key']

        ds['spent_minutes'] += minutes_spent

        # Обновить БД
        self.prime_storage.add_spent_minutes(
            emu_id, event_key, int(minutes_spent)
        )

        logger.info(
            f"[{self.emulator_name}] 📊 Прогресс ДС: "
            f"{ds['spent_minutes']:.0f}/{ds['target_minutes']} мин"
        )

    def _finalize_ds(self, ds: Dict, event: Dict):
        """Финализировать ДС — пометить completed если набрали очки."""
        if ds['spent_minutes'] >= ds['target_minutes']:
            self._set_completed(event['event_key'])
        else:
            logger.info(
                f"[{self.emulator_name}] ДС {event['event_key']}: "
                f"потрачено {ds['spent_minutes']:.0f}/{ds['target_minutes']} мин"
            )

    def _set_completed(self, event_key: str):
        """Пометить ДС как завершённый."""
        emu_id = self.emulator.get('id')

        ds = self.session_state.get('prime_times', {})
        ds['completed'] = True
        self.session_state['prime_times'] = ds

        self.prime_storage.mark_completed(emu_id, event_key)
        logger.success(
            f"[{self.emulator_name}] 🎉 ДС {event_key} завершён!"
        )

    def _set_skip(self, event_key: str, reason: str):
        """Пометить ДС как пропущенный."""
        emu_id = self.emulator.get('id')

        ds = self.session_state.get('prime_times', {})
        ds['event_key'] = event_key
        ds['skip_reason'] = reason
        ds['completed'] = False
        self.session_state['prime_times'] = ds

        self.prime_storage.mark_skipped(emu_id, event_key, reason)
        logger.info(
            f"[{self.emulator_name}] ⏭️ ДС {event_key} пропущен: {reason}"
        )