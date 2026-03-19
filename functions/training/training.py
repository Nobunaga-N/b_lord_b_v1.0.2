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