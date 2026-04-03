"""
Функция: TrainingFunction — тренировка войск

Оркестратор, связывающий:
- TrainingDatabase    — БД слотов, юнитов, уровни зданий
- TrainingNavigation  — навигация + цикл обучения
- NavigationPanel     — переход к зданию через панель
- BuildingDatabase    — сканирование уровня здания (если нет в БД)

Два типа войск:
- Плотоядные (Логово Плотоядных): Т4 Шакал / Т5 Гривистый Волк
  (Т5 разблокируется при уровне здания >= 13)
- Всеядные (Логово Всеядных): всегда Т1 Макака

1 слот тренировки на здание (аналог строителя).

Контракт execute():
- return True  = ситуация обработана (включая заморозку)
- return False = критическая ошибка → автозаморозка через run()

Версия: 1.0
Дата создания: 2025-03-19
"""

import time
import math
from datetime import datetime
from typing import Optional

from functions.base_function import BaseFunction
from functions.training.training_database import (
    TrainingDatabase, TRAINING_BUILDINGS, BUILDING_TYPE_NAMES_RU,
)
from functions.training.training_navigation import TrainingNavigation
from functions.building.navigation_panel import NavigationPanel
from functions.building.building_database import BuildingDatabase
from utils.function_freeze_manager import function_freeze_manager
from utils.logger import logger
from functions.prime_times.ds_schedule import (
    get_current_event, is_safe_to_start,
)
from functions.prime_times.ds_navigator import parse_ds_points
from functions.prime_times.speedup_calculator import (
    calculate_plan, choose_drain_type, calculate_target_minutes,
    MAX_TARGET_HOURS,
)
from functions.prime_times.speedup_applier import drain_speedups
from functions.prime_times.prime_storage import PrimeStorage
from functions.backpack_speedups.backpack_storage import BackpackStorage
from utils.adb_controller import press_key
from utils.image_recognition import find_image
from gui.prime_times_settings_window import load_allowed_drain_types


class TrainingFunction(BaseFunction):
    """
    Оркестратор тренировки войск

    execute() обрабатывает оба здания за один вызов:
    1. Плотоядные (carnivore)
    2. Всеядные (omnivore)
    """

    FUNCTION_NAME = 'training'

    # Заморозка при нехватке ресурсов (часы)
    FREEZE_HOURS_NO_RESOURCES = 4

    def __init__(self, emulator, session_state=None):
        super().__init__(emulator, session_state)
        self.name = "TrainingFunction"

        # Ленивая инициализация подмодулей
        self._db = None
        self._nav = None
        self._panel = None
        self._building_db = None

    # ==================== ЛЕНИВЫЕ СВОЙСТВА ====================

    @property
    def db(self) -> TrainingDatabase:
        if self._db is None:
            self._db = TrainingDatabase()
        return self._db

    @property
    def nav(self) -> TrainingNavigation:
        if self._nav is None:
            self._nav = TrainingNavigation()
        return self._nav

    @property
    def panel(self) -> NavigationPanel:
        if self._panel is None:
            self._panel = NavigationPanel()
        return self._panel

    @property
    def building_db(self) -> BuildingDatabase:
        if self._building_db is None:
            self._building_db = BuildingDatabase()
        return self._building_db

    # ==================== ПЛАНИРОВЩИК ====================

    @staticmethod
    def get_next_event_time(emulator_id: int) -> Optional[datetime]:
        """
        Когда тренировке потребуется эмулятор?

        Логика:
        1. Функция заморожена → время разморозки
        2. Нет данных (слоты не созданы) → datetime.min (первый запуск)
        3. Есть свободный слот → datetime.now()
        4. Все заняты → ближайший finish_time
        5. Все заняты, но finish_time нет → None

        Returns:
            datetime или None
        """
        # 1. Заморожена?
        if function_freeze_manager.is_frozen(emulator_id, 'training'):
            unfreeze = function_freeze_manager.get_unfreeze_time(
                emulator_id, 'training'
            )
            return unfreeze

        db = TrainingDatabase()

        # 2. Слоты существуют?
        free = db.get_free_slots(emulator_id)
        has_active = db.has_active_training(emulator_id)

        if not free and not has_active:
            # Нет данных → первый запуск
            return datetime.min

        # 3. Есть свободный слот?
        # Сначала проверим: может, есть завершившиеся
        db.clear_finished_slots(emulator_id)
        free = db.get_free_slots(emulator_id)

        if free:
            return datetime.now()

        # 4. Все заняты → ближайший finish
        nearest = db.get_nearest_finish_time(emulator_id)
        return nearest

    # ==================== can_execute ====================

    def can_execute(self) -> bool:
        """
        Можно ли тренировать сейчас?

        Условия:
        1. Функция не заморожена
        2. Есть хотя бы один свободный слот
        """
        emu_id = self.emulator.get('id')

        # 1. Заморожена?
        if function_freeze_manager.is_frozen(emu_id, self.FUNCTION_NAME):
            return False

        # 2. Инициализация слотов (если первый запуск)
        self.db.ensure_initialized(emu_id)

        # 3. Освободить завершившиеся
        self.db.clear_finished_slots(emu_id)

        # 4. Есть свободные слоты?
        free_slots = self.db.get_free_slots(emu_id)
        if not free_slots:
            logger.debug(
                f"[{self.emulator_name}] 🎓 Все слоты тренировки заняты"
            )
            return False

        return True

    # ==================== execute ====================

    def execute(self):
        """
        Главный метод — тренировка войск

        Алгоритм:
        1. Инициализация (слоты + здания в БД)
        2. Сканирование уровней зданий (если нужно)
        3. Для каждого свободного слота:
           a. Определить тир
           b. Навигация к зданию
           c. Обучение
           d. Обработка результата
        4. Возврат True

        Returns:
            True  — всё обработано (включая заморозку при нехватке)
            False — критическая ошибка навигации
        """
        emu_id = self.emulator.get('id')

        logger.info(
            f"[{self.emulator_name}] 🎓 === Тренировка войск ==="
        )

        # ШАГ 1: Инициализация
        self.db.ensure_initialized(emu_id)

        # ШАГ 2: Точечная проверка/создание зданий в buildings
        if not self._ensure_building_levels(emu_id):
            # Не удалось определить уровни — не критично, продолжаем
            logger.warning(
                f"[{self.emulator_name}] ⚠️ Не удалось определить "
                f"уровни зданий тренировки, используем fallback"
            )

        # ШАГ 3: Освободить завершившиеся слоты
        freed = self.db.clear_finished_slots(emu_id)
        if freed:
            logger.info(
                f"[{self.emulator_name}] 🔓 Освобождено слотов: {freed}"
            )

        # ШАГ 4: Обработка каждого свободного слота
        free_slots = self.db.get_free_slots(emu_id)

        if not free_slots:
            logger.info(
                f"[{self.emulator_name}] ✅ Все слоты заняты, "
                f"тренировка не требуется"
            )
            return True

        logger.info(
            f"[{self.emulator_name}] 📋 Свободные слоты: "
            f"{[BUILDING_TYPE_NAMES_RU.get(s, s) for s in free_slots]}"
        )

        for building_type in free_slots:
            success = self._train_one(emu_id, building_type)

            if success is None:
                # Заморозка (no_resources) — уже обработана внутри
                # Продолжаем к следующему слоту
                continue

            if not success:
                # Критическая ошибка навигации
                return False

        # === ПРАЙМ ТАЙМ (точка А — тренировка) ===
        self._handle_prime_time()

        logger.success(
            f"[{self.emulator_name}] ✅ Тренировка войск завершена"
        )
        return True

    # ==================== ВНУТРЕННИЕ МЕТОДЫ ====================

    def _ensure_building_levels(self, emu_id: int) -> bool:
        """
        Убедиться что уровни зданий тренировки известны

        1. ensure_buildings_in_db() — проверить/создать записи
        2. Для зданий с level=0 — сканировать через NavigationPanel

        Returns:
            True — все уровни известны
            False — хотя бы один уровень не удалось определить
        """
        buildings_status = self.db.ensure_buildings_in_db(emu_id)

        all_known = True

        for btype, level_known in buildings_status.items():
            if level_known:
                continue

            # Нужно сканировать
            building_name = TRAINING_BUILDINGS[btype]['building_name']
            logger.info(
                f"[{self.emulator_name}] 🔍 Сканирование уровня: "
                f"{building_name}"
            )

            success = self.building_db.scan_building_level(
                self.emulator, building_name
            )

            if success:
                level = self.db.get_building_level(emu_id, btype)
                logger.success(
                    f"[{self.emulator_name}] ✅ {building_name} → "
                    f"Lv.{level}"
                )
            else:
                logger.warning(
                    f"[{self.emulator_name}] ⚠️ Не удалось "
                    f"просканировать {building_name}"
                )
                all_known = False

        return all_known

    def _train_one(self, emu_id: int, building_type: str) -> Optional[bool]:
        """
        Обучить один тип войск

        Args:
            building_type: 'carnivore' / 'omnivore'

        Returns:
            True  — тренировка запущена
            None  — нехватка ресурсов (заморожено)
            False — критическая ошибка навигации
        """
        type_name = BUILDING_TYPE_NAMES_RU.get(building_type, building_type)
        building_name = TRAINING_BUILDINGS[building_type]['building_name']

        # Определить тир
        if building_type == 'omnivore':
            tier = 1
        else:
            tier = self.db.get_carnivore_tier(emu_id)

        logger.info(
            f"[{self.emulator_name}] 🎓 {type_name}: "
            f"Т{tier} ({building_name})"
        )

        # Навигация к зданию через NavigationPanel
        nav_result = self.panel.navigate_to_building(
            self.emulator, building_name
        )

        if not nav_result:
            logger.error(
                f"[{self.emulator_name}] ❌ Не удалось перейти к "
                f"{building_name}"
            )
            self._reset_nav_state()
            return False

        # Обучение
        status, timer_seconds, unit_count = self.nav.train_troops(
            self.emulator, building_type, tier
        )

        # Сброс nav_state после работы со зданием
        self._reset_nav_state()

        # Обработка результата
        if status == "started":
            # Записать в БД
            if timer_seconds:
                self.db.start_training(
                    emu_id, building_type, tier, timer_seconds
                )
            else:
                # Таймер не распознан — ставим 30 мин по умолчанию
                logger.warning(
                    f"[{self.emulator_name}] ⚠️ Таймер не распознан, "
                    f"используем 30 мин по умолчанию"
                )
                self.db.start_training(
                    emu_id, building_type, tier, 1800
                )

            # Обновить количество юнитов (если распознано)
            if unit_count is not None:
                from functions.training.training_database import TROOP_INFO
                troop_info = TROOP_INFO.get(building_type, {}).get(tier)
                if troop_info:
                    self.db.update_troop_count(
                        emu_id,
                        troop_info['name'],
                        tier,
                        building_type,
                        unit_count,
                    )

            return True

        elif status == "no_resources":
            # Заморозить функцию
            function_freeze_manager.freeze(
                emulator_id=emu_id,
                function_name=self.FUNCTION_NAME,
                hours=self.FREEZE_HOURS_NO_RESOURCES,
                reason=f"Нехватка ресурсов для {type_name} Т{tier}",
            )
            return None  # Обработано, не критично

        elif status == "already_training":
            # Слот занят — обновим БД на всякий случай
            logger.info(
                f"[{self.emulator_name}] ℹ️ {type_name}: "
                f"тренировка уже идёт"
            )
            return True

        else:
            # "error" — критическая ошибка
            logger.error(
                f"[{self.emulator_name}] ❌ Ошибка при обучении "
                f"{type_name} Т{tier}"
            )
            return False

    def _reset_nav_state(self):
        """Сбросить состояние навигации после работы со зданием"""
        try:
            self.panel.nav_state.close_panel()
        except Exception:
            pass

    # ==================== PRIME TIME (ТОЧКА А) ====================
    def _handle_prime_time(self):
        """
        Проверить и выполнить drain ускорений тренировки в ДС.

        Вызывается ПОСЛЕ основного цикла тренировки (оба слота заняты).
        Бот находится в поместье.

        Не влияет на return execute(). Все ошибки обрабатываются внутри.
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        try:
            # 1. prime_times включён?
            active_funcs = self.session_state.get('_active_functions', [])
            if 'prime_times' not in active_funcs:
                return

            # 2. Активный ДС?
            now = datetime.now()
            event = get_current_event(now)
            if event is None:
                return

            event_key = event['event_key']

            # 3. Уже завершён?
            ds = self.session_state.get('prime_times')
            if ds and ds.get('completed') and ds.get('event_key') == event_key:
                return

            prime_st = PrimeStorage()
            if prime_st.is_completed(emu_id, event_key):
                return

            # 4. Время?
            progress = prime_st.get_progress(emu_id, event_key)
            spent = float(progress['spent_minutes']) if progress else 0.0

            if spent <= 0 and not is_safe_to_start(now, min_minutes=5):
                return

            # 5. Инициализация session_state
            if ds is None or ds.get('event_key') != event_key:
                ds = self._init_prime_session(event, prime_st)
                if ds is None:
                    return

            # 6. drain_type = training?
            if ds.get('skip_reason') or ds.get('completed'):
                return

            if ds['drain_type'] != 'training':
                return

            # 7. Drain
            logger.info(
                f"[{emu_name}] 🎯 Prime Time (training): "
                f"target={ds['target_minutes']} мин, "
                f"spent={ds['spent_minutes']:.0f} мин"
            )
            self._drain_training_in_prime(ds, event, prime_st)

        except Exception as e:
            logger.error(f"[{emu_name}] ❌ Ошибка в _handle_prime_time: {e}")

    def _init_prime_session(
            self, event: dict, prime_st: PrimeStorage
    ) -> dict | None:
        """
        Инициализировать session_state['prime_times'].

        FIX: Если ds_progress уже есть — используем сохранённый
        target_minutes вместо пересчёта из текущих очков.
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name
        event_key = event['event_key']
        ppm = event['points_per_min']

        bp_storage = BackpackStorage()
        inventory = bp_storage.get_inventory(emu_id)
        if not inventory:
            return None

        has_buildings = True
        try:
            from functions.building.building_database import BuildingDatabase
            bdb = BuildingDatabase()
            has_buildings = bdb.has_buildings_to_upgrade(emu_id)
        except Exception:
            pass

        allowed = load_allowed_drain_types(emu_id)
        drain_type, _ = choose_drain_type(
            inventory, event['type'], has_buildings,
            allowed_drain_types=allowed,
        )
        if drain_type is None:
            self._set_prime_skip(event_key, 'not_enough_speedups', prime_st)
            return self.session_state.get('prime_times')

        # ── FIX: Проверяем ds_progress ДО парсинга очков ──
        progress = prime_st.get_progress(emu_id, event_key)

        if progress and progress['status'] == 'in_progress':
            # ═══ ВОССТАНОВЛЕНИЕ ═══
            target_min = int(progress['target_minutes'])
            spent = float(progress['spent_minutes'])
            target_shell = int(progress.get('target_shell', 2))

            logger.info(
                f"[{emu_name}] 🔄 Восстановлено из ds_progress: "
                f"{spent:.0f}/{target_min} мин (shell {target_shell})"
            )

            # Парсим очки информационно (для session_state)
            ds_points = parse_ds_points(self.emulator)
            if ds_points is None:
                ds_points = {'current': 0, 'shell_1': 0, 'shell_2': 0}
        else:
            # ═══ ПЕРВЫЙ ЗАПУСК ═══
            ds_points = parse_ds_points(self.emulator)
            if ds_points is None:
                from utils.function_freeze_manager import (
                    function_freeze_manager,
                )
                function_freeze_manager.freeze(
                    emu_id, 'prime_times', hours=1,
                    reason="Ошибка парсинга очков ДС",
                )
                return None

            target_shell = 2
            target_min = calculate_target_minutes(
                ds_points['current'], ds_points['shell_2'], ppm
            )
            if target_min > MAX_TARGET_HOURS * 60:
                target_min_1 = calculate_target_minutes(
                    ds_points['current'], ds_points['shell_1'], ppm
                )
                if target_min_1 <= MAX_TARGET_HOURS * 60:
                    target_min = target_min_1
                    target_shell = 1
                else:
                    self._set_prime_skip(
                        event_key, '>65h', prime_st
                    )
                    return self.session_state.get('prime_times')

            if target_min <= 0:
                self._set_prime_completed(event_key, prime_st)
                return self.session_state.get('prime_times')

            spent = 0.0

        ds = {
            'event_type': event['type'],
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
        prime_st.save_progress(
            emu_id, event_key, target_min,
            int(spent), target_shell, 'in_progress',
        )

        logger.info(
            f"[{emu_name}] Prime init: drain={drain_type}, "
            f"target={target_min} мин (shell {target_shell})"
        )
        return ds

    def _drain_training_in_prime(
        self, ds: dict, event: dict, prime_st: PrimeStorage
    ):
        """
        Цикл drain тренировочных ускорений для ДС.

        Архитектура: двойной цикл.
        - Внешний: обеспечивает тренировку активной + навигация к окну ускорений
        - Внутренний: drain по пачкам (парсим таймер → план на пачку → drain →
          если завершилось → новая пачка → continue)

        Ключевое: calculate_plan получает таймер ТЕКУЩЕЙ ПАЧКИ, а не весь ДС.
        Это обеспечивает правильный подбор номиналов без перерасхода.

        Три сценария:
        1) Слот свободен → train_troops() → ESC → проваливаемся в (2)
        2) Слот занят → навигация → окно ускорений → внутренний цикл
        3) Тренировка завершилась → "Обучение" → новая пачка → "Ускорение" → continue
        """
        import os
        from utils.adb_controller import tap
        from functions.prime_times.speedup_applier import _parse_remaining_timer
        from utils.ocr_engine import OCREngine

        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name
        bp_storage = BackpackStorage()

        building_type = 'carnivore'
        building_name = TRAINING_BUILDINGS[building_type]['building_name']

        BASE_DIR = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        speedup_btn_path = os.path.join(
            BASE_DIR, 'data', 'templates', 'prime_times', 'button_speedup.png'
        )
        training_btn_path = os.path.join(
            BASE_DIR, 'data', 'templates', 'training', 'button_training.png'
        )

        ocr = OCREngine()

        # ════════════════════════════════════════════
        # ВНЕШНИЙ ЦИКЛ: навигация + запуск тренировки
        # ════════════════════════════════════════════
        while ds['spent_minutes'] < ds['target_minutes']:
            # ── Проверка времени ДС ──
            if not is_safe_to_start(min_minutes=5):
                if ds['spent_minutes'] <= 0:
                    logger.info(f"[{emu_name}] Prime: мало времени до конца ДС")
                break

            # ── ШАГ 1: Убедиться что тренировка активна ──
            self.db.clear_finished_slots(emu_id)
            slot_free = self.db.is_slot_free(emu_id, building_type)

            if slot_free:
                logger.info(f"[{emu_name}] Prime: слот свободен, ставим зверей")

                nav_ok = self.panel.navigate_to_building(
                    self.emulator, building_name
                )
                if not nav_ok:
                    logger.error(
                        f"[{emu_name}] Prime: навигация к "
                        f"{building_name} провалилась"
                    )
                    self._reset_nav_state()
                    break

                tier = self.db.get_carnivore_tier(emu_id)
                status, timer_sec, _ = self.nav.train_troops(
                    self.emulator, building_type, tier
                )
                self._reset_nav_state()  # train_troops() → ESC → поместье

                if status != 'started':
                    logger.warning(
                        f"[{emu_name}] Prime: train_troops → {status}"
                    )
                    break

                if timer_sec:
                    self.db.start_training(
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
                    f"[{emu_name}] Prime: навигация к "
                    f"{building_name} провалилась"
                )
                self._reset_nav_state()
                break

            tap(self.emulator, 268, 517)
            time.sleep(1.5)

            if not self.nav._click_training_icon(self.emulator):
                logger.error(
                    f"[{emu_name}] Prime: иконка 'Обучение' не найдена"
                )
                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                self._reset_nav_state()
                break

            if not self._click_speedup_button(speedup_btn_path):
                logger.error(
                    f"[{emu_name}] Prime: кнопка 'Ускорение' не найдена"
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
                    f"[{emu_name}] Prime пачка: "
                    f"таймер={batch_timer_min}мин, "
                    f"осталось ДС={remaining_ds_min}мин, "
                    f"batch_target={batch_target}мин"
                )

                # ── План на ЭТУ ПАЧКУ ──
                inventory = bp_storage.get_inventory(emu_id)

                has_buildings = True
                try:
                    has_buildings = (
                        self.building_db.has_buildings_to_upgrade(emu_id)
                    )
                except Exception:
                    pass

                # ── FIX: timers и calculate_plan ВЫНЕСЕНЫ из except ──
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
                        f"[{emu_name}] Prime: план пустой — "
                        f"{plan.skip_reason}"
                    )
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                # ── Drain этой пачки ──
                result = drain_speedups(
                    self.emulator, plan, 'training',
                    self.session_state
                )

                # ── Обновляем прогресс ──
                ds['spent_minutes'] += result.minutes_spent
                prime_st.add_spent_minutes(
                    emu_id, event['event_key'],
                    int(result.minutes_spent)
                )
                logger.info(
                    f"[{emu_name}] 📊 Прогресс ДС: "
                    f"{ds['spent_minutes']:.0f}/{ds['target_minutes']} мин"
                )

                if not result.building_completed:
                    # Тренировка ещё идёт → ускорения по плану потрачены
                    # Закрываем окно ускорений + окно тренировки
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                # ═══ СЦЕНАРИЙ 3: Тренировка завершилась ═══
                # Окно ускорений закрылось → бот видит окно зверей
                logger.info(
                    f"[{emu_name}] 🎓 Тренировка завершилась!"
                )
                self.db.clear_finished_slots(emu_id)

                # Проверяем: набрали ли очки ДС?
                if ds['spent_minutes'] >= ds['target_minutes']:
                    logger.info(
                        f"[{emu_name}] Prime: ДС цель достигнута, "
                        f"выходим"
                    )
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                # Кликаем "Обучение" → ставим новых зверей
                if not self._click_training_button(training_btn_path):
                    logger.warning(
                        f"[{emu_name}] Prime: кнопка 'Обучение' "
                        f"не найдена"
                    )
                    break

                logger.info(
                    f"[{emu_name}] Prime: новые звери поставлены"
                )

                # Парсим таймер новой пачки
                new_timer_sec = self.nav._parse_training_timer(
                    self.emulator
                )
                if new_timer_sec:
                    tier = self.db.get_carnivore_tier(emu_id)
                    self.db.start_training(
                        emu_id, building_type, tier, new_timer_sec
                    )

                # "Ускорение" → обратно в окно ускорений
                if not self._click_speedup_button(speedup_btn_path):
                    logger.error(
                        f"[{emu_name}] Prime: кнопка 'Ускорение' "
                        f"не найдена"
                    )
                    press_key(self.emulator, "ESC")
                    time.sleep(0.5)
                    break

                time.sleep(1.0)
                # continue → внутренний цикл: следующая пачка

            # Внутренний цикл завершён — внешний тоже завершаем.
            # Повторная навигация не нужна: если внутренний цикл
            # break-нулся, значит либо цель достигнута, либо ошибка,
            # либо ДС закончился. Во всех случаях продолжать нет смысла.
            self._reset_nav_state()
            break

        # ════════════════════════════════════════════
        # ФИНАЛИЗАЦИЯ
        # ════════════════════════════════════════════
        if ds['spent_minutes'] >= ds['target_minutes']:
            self._set_prime_completed(event['event_key'], prime_st)
        else:
            logger.info(
                f"[{emu_name}] Prime training: итого "
                f"{ds['spent_minutes']:.0f}/{ds['target_minutes']} мин"
            )

    # ── Хелперы для кликов по шаблонам ──
    def _click_speedup_button(self, template_path: str) -> bool:
        """
        Найти и кликнуть кнопку "Ускорение" (button_speedup.png).

        Кнопка находится внутри окна тренировки, под таймером.

        Returns:
            True если кнопка найдена и нажата
        """
        import os
        if not os.path.exists(template_path):
            logger.warning("⚠️ Шаблон button_speedup.png не найден")
            return False

        for attempt in range(3):
            result = find_image(
                self.emulator, template_path, threshold=0.85
            )
            if result:
                from utils.adb_controller import tap
                tap(self.emulator, x=result[0], y=result[1])
                logger.debug(
                    f"[{self.emulator_name}] ✅ Кнопка 'Ускорение' нажата "
                    f"({result[0]}, {result[1]})"
                )
                return True
            time.sleep(0.5)

        logger.warning(f"[{self.emulator_name}] ⚠️ Кнопка 'Ускорение' не найдена")
        return False

    def _click_training_button(self, template_path: str) -> bool:
        """
        Найти и кликнуть кнопку "Обучение" (button_training.png).

        Используется в сценарии 3: после завершения ускорения
        тренировки, бот видит окно выбора зверей с кнопкой "Обучение".

        Returns:
            True если кнопка найдена и нажата
        """
        import os
        if not os.path.exists(template_path):
            logger.warning("⚠️ Шаблон button_training.png не найден")
            return False

        time.sleep(1.5)  # пауза чтобы окно полностью отрисовалось

        for attempt in range(3):
            result = find_image(
                self.emulator, template_path, threshold=0.85
            )
            if result:
                from utils.adb_controller import tap
                tap(self.emulator, x=result[0], y=result[1])
                time.sleep(2.0)  # ждём пока тренировка запустится
                logger.debug(
                    f"[{self.emulator_name}] ✅ Кнопка 'Обучение' нажата"
                )
                return True
            time.sleep(0.5)

        logger.warning(f"[{self.emulator_name}] ⚠️ Кнопка 'Обучение' не найдена")
        return False

    def _reset_nav_state(self):
        """Сбросить состояние навигации."""
        try:
            self.panel.nav_state.close_panel()
        except Exception:
            pass

    def _set_prime_completed(self, event_key: str, prime_st: PrimeStorage):
        emu_id = self.emulator.get('id')
        ds = self.session_state.get('prime_times', {})
        ds['completed'] = True
        ds['event_key'] = event_key
        self.session_state['prime_times'] = ds
        prime_st.mark_completed(emu_id, event_key)
        logger.success(f"[{self.emulator_name}] 🎉 Prime: ДС {event_key} завершён!")

    def _set_prime_skip(self, event_key: str, reason: str, prime_st: PrimeStorage):
        emu_id = self.emulator.get('id')
        ds = self.session_state.get('prime_times', {})
        ds['event_key'] = event_key
        ds['skip_reason'] = reason
        ds['completed'] = False
        self.session_state['prime_times'] = ds
        prime_st.mark_skipped(emu_id, event_key, reason)