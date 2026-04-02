"""
Главный класс функции строительства
Объединяет NavigationPanel, BuildingUpgrade, BuildingConstruction, BuildingDatabase

ОБНОВЛЕНО: Интеграция первичного сканирования + обновленная БД

Версия: 2.0
Дата обновления: 2025-01-21
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from functions.base_function import BaseFunction
from functions.building.navigation_panel import NavigationPanel
from functions.building.building_upgrade import BuildingUpgrade
from functions.building.building_construction import BuildingConstruction
from functions.building.building_database import BuildingDatabase
from utils.logger import logger
from utils.adb_controller import press_key
from utils.adb_controller import press_key, execute_command, get_adb_device
from core.game_launcher import GameLauncher
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


class BuildingFunction(BaseFunction):
    """
    Главная функция строительства

    Процесс:
    1. Инициализация (первый запуск)
    2. Первичное сканирование (если нужно)
    3. Проверить свободных строителей
    4. Определить следующее здание (BuildingDatabase)
    5. Перейти к зданию (NavigationPanel)
    6. Улучшить / Построить здание (BuildingUpgrade / BuildingConstruction)
    7. Обновить БД
    8. Повторить пока есть свободные строители
    """

    def __init__(self, emulator, session_state=None):
        """Инициализация функции строительства"""
        super().__init__(emulator, session_state)
        self.name = "BuildingFunction"

        # Инициализация компонентов (БЕЗ ИЗМЕНЕНИЙ)
        self.panel = NavigationPanel()
        self.upgrade = BuildingUpgrade()
        self.construction = BuildingConstruction()
        self.db = BuildingDatabase()

        logger.info(f"[{self.emulator_name}] ✅ BuildingFunction инициализирована")

    @staticmethod
    def get_next_event_time(emulator_id: int):
        """
        Когда строительству потребуется эмулятор?

        Лёгкая проверка через БД без запуска эмулятора.
        Вызывается планировщиком для определения времени запуска.

        Логика:
        1. Заморожена → время разморозки
        2. Нет записей зданий → datetime.min (новый эмулятор)
        3. Здания есть, но строителей нет → datetime.min (частичная инициализация)
        4. Есть свободный строитель + есть что строить → datetime.now()
        5. Есть свободный строитель, но строить нечего → None
        6. Все строители заняты + есть что строить → время ближайшего освобождения
        7. Все строители заняты + строить нечего → None

        Returns:
            datetime — когда нужен эмулятор
            None — эмулятор не нужен для строительства

        ИСПРАВЛЕНО: Проверяет function_freeze_manager (in-memory)
        в первую очередь, ДО проверок через БД.
        """
        # ===== НОВОЕ: Проверка in-memory заморозки =====
        from utils.function_freeze_manager import function_freeze_manager

        if function_freeze_manager.is_frozen(emulator_id, 'building'):
            unfreeze_at = function_freeze_manager.get_unfreeze_time(
                emulator_id, 'building'
            )
            if unfreeze_at:
                return unfreeze_at
            return None

        db = BuildingDatabase()

        try:
            # 1. Новый эмулятор?
            if not db.has_buildings(emulator_id):
                return datetime.min

            # 2. Частичная инициализация? (здания есть, строителей нет)
            if not db.has_builders(emulator_id):
                return datetime.min

            # 3. Свободный строитель?
            free_builder = db.get_free_builder(emulator_id)

            # 4. Есть что строить?
            has_work = db.has_buildings_to_upgrade(emulator_id)

            if not has_work:
                return None

            if free_builder is not None:
                return datetime.now()

            # 5. Все заняты → ближайшее освобождение
            nearest = db.get_nearest_builder_finish_time(emulator_id)
            return nearest

        except Exception as e:
            logger.error(
                f"[Emulator {emulator_id}] Ошибка в "
                f"BuildingFunction.get_next_event_time: {e}"
            )
            return None

    def _first_time_initialization(self) -> bool:
        """
        Инициализация при первом запуске эмулятора

        1. Проверить есть ли записи в БД
        2. Если нет — создать записи для всех зданий + строителей + первичный скан
        3. Если записи зданий есть, но строителей нет — досоздать строителей + скан
        4. Если всё есть — проверить нужен ли первичный скан

        Returns:
            bool: True если инициализация успешна
        """
        emulator_id = self.emulator.get('id', 0)

        with self.db.db_lock:
            cursor = self.db.conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) FROM buildings WHERE emulator_id = ?",
                (emulator_id,)
            )
            buildings_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM builders WHERE emulator_id = ?",
                (emulator_id,)
            )
            builders_count = cursor.fetchone()[0]

        # ── Случай 1: Полная инициализация (нет зданий вообще) ──
        if buildings_count == 0:
            logger.info(
                f"[{self.emulator_name}] 🆕 ПЕРВЫЙ ЗАПУСК — "
                f"Начало полной инициализации..."
            )
            return self._run_full_initialization()

        # ── Случай 2: Здания есть, строителей нет (частичная инициализация) ──
        if builders_count == 0:
            logger.warning(
                f"[{self.emulator_name}] ⚠️ Обнаружена частичная инициализация: "
                f"{buildings_count} зданий, 0 строителей. Досоздаём..."
            )
            return self._repair_initialization(buildings_count)

        # ── Случай 3: Всё есть — проверяем нужен ли первичный скан ──
        with self.db.db_lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM buildings "
                "WHERE emulator_id = ? AND current_level = 0 AND action = 'upgrade'",
                (emulator_id,)
            )
            unscanned_count = cursor.fetchone()[0]

        if unscanned_count > 10:
            # Много непросканированных зданий — скорее всего скан не проходил
            logger.warning(
                f"[{self.emulator_name}] ⚠️ {unscanned_count} зданий без уровня, "
                f"запускаю первичное сканирование..."
            )
            success = self.db.perform_initial_scan(self.emulator)
            if not success:
                logger.warning(
                    f"[{self.emulator_name}] ⚠️ Первичное сканирование "
                    f"завершено с ошибками"
                )
                # Не возвращаем False — можно продолжать работу

        logger.debug(
            f"[{self.emulator_name}] БД уже инициализирована "
            f"({buildings_count} зданий, {builders_count} строителей)"
        )
        return True

    def _run_full_initialization(self) -> bool:
        """
        Полная инициализация: строители + здания + первичный скан.
        Вызывается когда в БД нет записей зданий для этого эмулятора.
        """
        emulator_id = self.emulator.get('id', 0)

        # ШАГ 1: Определить количество строителей через OCR
        logger.info(f"[{self.emulator_name}] 🔍 Определение количества строителей...")
        busy, total = self.db.detect_builders_count(self.emulator)
        logger.info(f"[{self.emulator_name}] 🔨 Строители: {busy}/{total}")

        # ШАГ 2: Создать записи для всех зданий + строителей
        logger.info(f"[{self.emulator_name}] 📋 Создание записей в БД...")
        success = self.db.initialize_buildings_for_emulator(emulator_id, total)

        if not success:
            logger.error(f"[{self.emulator_name}] ❌ Ошибка инициализации БД")
            return False

        # ШАГ 3: Первичное сканирование
        logger.info(f"[{self.emulator_name}] 🔍 Запуск первичного сканирования...")
        success = self.db.perform_initial_scan(self.emulator)

        if not success:
            logger.warning(
                f"[{self.emulator_name}] ⚠️ Первичное сканирование "
                f"завершено с ошибками"
            )
            # Не возвращаем False — можно продолжать работу

        logger.success(f"[{self.emulator_name}] ✅ Инициализация завершена")
        return True

    def _repair_initialization(self, existing_buildings_count: int) -> bool:
        """
        Ремонт частичной инициализации: досоздать строителей и запустить скан.

        Ситуация: в БД есть записи зданий (например, от тренировки, которая
        точечно парсила 2 здания), но строители не созданы.

        Args:
            existing_buildings_count: сколько зданий уже есть в БД
        """
        emulator_id = self.emulator.get('id', 0)

        # ШАГ 1: Определить количество строителей через OCR
        logger.info(f"[{self.emulator_name}] 🔍 Определение количества строителей...")
        busy, total = self.db.detect_builders_count(self.emulator)
        logger.info(f"[{self.emulator_name}] 🔨 Строители: {busy}/{total}")

        with self.db.db_lock:
            cursor = self.db.conn.cursor()

            # ШАГ 2: Создать записи строителей (если не существуют)
            for slot in range(1, total + 1):
                cursor.execute(
                    "SELECT COUNT(*) FROM builders "
                    "WHERE emulator_id = ? AND builder_slot = ?",
                    (emulator_id, slot)
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute("""
                        INSERT INTO builders 
                        (emulator_id, builder_slot, is_busy)
                        VALUES (?, ?, 0)
                    """, (emulator_id, slot))

            self.db.conn.commit()

        logger.success(
            f"[{self.emulator_name}] ✅ Созданы записи строителей ({total} шт)"
        )

        # ШАГ 3: Доинициализировать здания (если их мало — добавляем остальные)
        full_buildings_list = self.db._extract_unique_buildings()
        expected_count = len(full_buildings_list)

        if existing_buildings_count < expected_count:
            logger.info(
                f"[{self.emulator_name}] 📋 В БД {existing_buildings_count}/{expected_count} "
                f"зданий, добавляю недостающие..."
            )
            self._add_missing_buildings(emulator_id, full_buildings_list)

        # ШАГ 4: Первичное сканирование (для всех зданий с level=0)
        logger.info(f"[{self.emulator_name}] 🔍 Запуск первичного сканирования...")
        success = self.db.perform_initial_scan(self.emulator)

        if not success:
            logger.warning(
                f"[{self.emulator_name}] ⚠️ Первичное сканирование "
                f"завершено с ошибками"
            )

        logger.success(
            f"[{self.emulator_name}] ✅ Ремонт инициализации завершён"
        )
        return True

    def _add_missing_buildings(self, emulator_id: int, full_list: list):
        """
        Добавить в БД здания которых ещё нет.
        Не трогает уже существующие записи (например точечно спарсенные тренировкой).
        """
        with self.db.db_lock:
            cursor = self.db.conn.cursor()
            added = 0

            for b in full_list:
                name = b['name']
                index = b.get('index')
                max_target = b['max_target_level']
                btype = b['type']
                action = b['action']

                # Проверяем: уже есть такая запись?
                if index is not None:
                    cursor.execute(
                        "SELECT COUNT(*) FROM buildings "
                        "WHERE emulator_id = ? AND building_name = ? "
                        "AND building_index = ?",
                        (emulator_id, name, index)
                    )
                else:
                    cursor.execute(
                        "SELECT COUNT(*) FROM buildings "
                        "WHERE emulator_id = ? AND building_name = ? "
                        "AND building_index IS NULL",
                        (emulator_id, name)
                    )

                if cursor.fetchone()[0] > 0:
                    continue  # Уже есть — не трогаем

                cursor.execute("""
                    INSERT INTO buildings 
                    (emulator_id, building_name, building_type, building_index,
                     current_level, target_level, status, action)
                    VALUES (?, ?, ?, ?, 0, ?, 'idle', ?)
                """, (emulator_id, name, btype, index, max_target, action))
                added += 1

            self.db.conn.commit()

            if added > 0:
                logger.info(
                    f"[{self.emulator_name}] ✅ Добавлено {added} "
                    f"недостающих зданий в БД"
                )

    def can_execute(self) -> bool:
        """
        Можно ли строить сейчас?

        Проверки:
        0. Инициализация при первом запуске
        1. Строительство не заморожено (через единый менеджер)
        2. Есть свободные строители
        3. Есть здания для прокачки
        """
        emulator_id = self.emulator.get('id', 0)

        # ПРОВЕРКА 0: Инициализация при первом запуске
        if not self._first_time_initialization():
            logger.error(f"[{self.emulator_name}] ❌ Ошибка инициализации")
            return False

        # ПРОВЕРКА 1: Заморозка (ЕДИНЫЙ МЕНЕДЖЕР)
        from utils.function_freeze_manager import function_freeze_manager

        if function_freeze_manager.is_frozen(emulator_id, 'building'):
            unfreeze_at = function_freeze_manager.get_unfreeze_time(
                emulator_id, 'building'
            )
            if unfreeze_at:
                logger.debug(
                    f"[{self.emulator_name}] ❄️ Строительство заморожено "
                    f"до {unfreeze_at.strftime('%H:%M:%S')}"
                )
            return False

        # ПРОВЕРКА 2: Свободные строители
        free_builder = self.db.get_free_builder(emulator_id)
        if free_builder is None:
            logger.debug(f"[{self.emulator_name}] 👷 Нет свободных строителей")
            return False

        # ПРОВЕРКА 3: Есть ли что строить
        next_building = self.db.get_next_building_to_upgrade(
            self.emulator, auto_scan=True
        )
        if not next_building:
            logger.debug(
                f"[{self.emulator_name}] 🎯 Все здания достигли целевого уровня"
            )
            return False

        logger.debug(
            f"[{self.emulator_name}] ✅ Можно строить: "
            f"следующее здание - {next_building['name']}"
        )
        return True

    def execute(self) -> bool:
        """
        Выполнить цикл строительства

        Процесс:
        1. Пока есть свободные строители
        2. Определить следующее здание
        3. Перейти и улучшить/построить
        4. Обновить БД
        5. Повторить

        КОНТРАКТ:
        - return True  → хотя бы одно здание обработано
                     ИЛИ ситуация обработана (заморозка через БД)
        - return False → критическая ошибка → автозаморозка через run()
        """
        emulator_id = self.emulator.get('id', 0)

        logger.info(f"[{self.emulator_name}] 🏗️ Начало цикла строительства")

        completed_count = self.db.check_and_update_completed_buildings(emulator_id)
        if completed_count > 0:
            logger.info(f"[{self.emulator_name}] 🎉 Завершено построек с прошлого "
                        f"цикла: {completed_count}")

        upgraded_count = 0
        constructed_count = 0
        failed = False
        resources_frozen = False

        # Цикл пока есть свободные строители
        while True:
            if self.db.is_emulator_frozen(emulator_id):
                logger.info(f"[{self.emulator_name}] ❄️ Эмулятор заморожен")
                break

            free_builder = self.db.get_free_builder(emulator_id)
            if free_builder is None:
                logger.info(f"[{self.emulator_name}] 👷 Нет свободных строителей")
                break

            next_building = self.db.get_next_building_to_upgrade(
                self.emulator, auto_scan=True
            )
            if not next_building:
                logger.info(f"[{self.emulator_name}] ✅ Все здания достигли "
                            f"целевого уровня")
                break

            building_name = next_building['name']
            building_index = next_building.get('index')
            current_level = next_building['current_level']
            target_level = next_building['target_level']
            action = next_building.get('action', 'upgrade')

            display_name = building_name
            if building_index is not None:
                display_name += f" #{building_index}"

            logger.info(f"[{self.emulator_name}] 🎯 Следующее здание: {display_name} "
                        f"(Lv.{current_level} → Lv.{target_level}) [action={action}]")

            if action == 'build':
                # ПОСТРОЙКА НОВОГО ЗДАНИЯ
                logger.info(f"[{self.emulator_name}] 🏗️ Постройка: {display_name}")

                press_key(self.emulator, "ESC")
                time.sleep(0.5)

                success, actual_level = self.construction.construct_building(
                    self.emulator, building_name, building_index
                )

                if success:
                    logger.success(f"[{self.emulator_name}] ✅ Здание построено: "
                                   f"{display_name}")
                    self.db.update_building_after_construction(
                        emulator_id, building_name, building_index,
                        actual_level=actual_level
                    )
                    constructed_count += 1
                    continue
                else:
                    logger.warning(f"[{self.emulator_name}] ⚠️ Не удалось построить "
                                   f"{display_name}")
                    failed = True
                    break

            else:
                # УЛУЧШЕНИЕ СУЩЕСТВУЮЩЕГО ЗДАНИЯ
                expected_level = current_level
                success = self.panel.navigate_to_building(
                    self.emulator, building_name,
                    building_index=building_index,
                    expected_level=expected_level
                )

                if not success:
                    logger.warning(f"[{self.emulator_name}] ⚠️ Не удалось перейти "
                                   f"к {display_name}")
                    failed = True
                    break

                detected_level = self.panel.last_detected_level

                upgrade_success, timer_seconds = self.upgrade.upgrade_building(
                    self.emulator,
                    building_name=building_name,
                    building_index=building_index
                )

                # ═══════════════════════════════════════════════
                # 🆕 ЛОРД: специальная обработка
                # ═══════════════════════════════════════════════
                if next_building['is_lord'] and upgrade_success:
                    lord_result = self._handle_lord_upgrade(
                        emulator_id, detected_level, current_level,
                        timer_seconds, free_builder
                    )
                    if lord_result in ('upgraded', 'timer_set'):
                        upgraded_count += 1
                    # Всегда break — пока Лорд улучшается,
                    # все остальные строители простаивают
                    break

                # ═══════════════════════════════════════════════
                # Обычное здание (НЕ Лорд) — без изменений
                # ═══════════════════════════════════════════════
                elif upgrade_success and timer_seconds and timer_seconds > 0:
                    timer_finish = datetime.now() + timedelta(seconds=timer_seconds)
                    self.db.set_building_upgrading(
                        emulator_id, building_name, building_index,
                        timer_finish, free_builder,
                        actual_level=detected_level
                    )
                    upgraded_count += 1
                    logger.success(f"[{self.emulator_name}] ✅ {display_name} "
                                   f"улучшение начато "
                                   f"({self._format_time(timer_seconds)})")

                elif upgrade_success and (timer_seconds == 0 or timer_seconds is None):
                    new_level = (detected_level or current_level) + 1
                    self.db.update_building_level(
                        emulator_id, building_name, building_index, new_level
                    )
                    upgraded_count += 1
                    logger.success(f"[{self.emulator_name}] ⚡ {display_name} "
                                   f"мгновенное улучшение → Lv.{new_level}")

                else:
                    self.db.freeze_emulator(emulator_id, hours=6,
                                            reason="Нехватка ресурсов")
                    logger.warning(f"[{self.emulator_name}] ❄️ Заморозка на 6 часов")
                    resources_frozen = True
                    break

        # === ПРАЙМ ТАЙМ (точка А — строительство) ===
        self._handle_prime_time()

        # === ИТОГ ===
        total = upgraded_count + constructed_count
        logger.info(f"[{self.emulator_name}] 📊 Строительство: "
                    f"улучшено={upgraded_count}, построено={constructed_count}")

        # Ситуация обработана (ресурсы закончились, заморозка уже в БД)
        if resources_frozen:
            return True

        # Хотя бы одно здание обработано — успех
        if total > 0:
            return True

        # Ничего не сделали, но и ошибок не было (всё построено / нет строителей)
        if not failed:
            return True

        # ===== Критическая ошибка: ничего не сделали + был провал =====
        # return False → run() автоматически заморозит
        return False

    def _handle_lord_upgrade(self, emulator_id: int, detected_level,
                             current_level: int, initial_timer,
                             builder_slot: int) -> str:
        """
        Специальная обработка улучшения Лорда.

        После upgrade_building() — автоускорение + обработка результата.
        Пока Лорд улучшается — все остальные строители простаивают.

        Returns:
            'upgraded' — Лорд улучшился мгновенно (игра перезапущена)
            'timer_set' — Лорд улучшается, таймер записан
            'failed' — ошибка
        """
        lord_level = detected_level or current_level
        expected_new = lord_level + 1

        logger.info(f"[{self.emulator_name}] 👑 Обработка Лорда "
                    f"(Lv.{lord_level} → Lv.{expected_new})")

        # Мгновенное завершение ДО автоускорения (помощь альянса)
        if initial_timer is None or initial_timer == 0:
            logger.info(f"[{self.emulator_name}] ⚡ Лорд завершился мгновенно "
                        f"(до автоускорения)")
            return self._lord_instant_finish(emulator_id, lord_level, expected_new)

        # Таймер > 0 — пробуем автоускорение
        speedup_result = self.upgrade.speedup_lord(self.emulator)
        status = speedup_result['status']
        remaining = speedup_result.get('timer_seconds')

        if status == 'instant_upgrade':
            return self._lord_instant_finish(emulator_id, lord_level, expected_new)

        elif status in ('timer_remaining', 'no_speedups'):
            timer_val = remaining or initial_timer
            timer_finish = datetime.now() + timedelta(seconds=timer_val)
            self.db.set_building_upgrading(
                emulator_id, "Лорд", None,
                timer_finish, builder_slot,
                actual_level=lord_level
            )
            label = "частично ускорен" if status == 'timer_remaining' else "без ускорения"
            logger.info(f"[{self.emulator_name}] ⏳ Лорд улучшается ({label}): "
                        f"{self._format_time(timer_val)}. Строители простаивают.")
            return 'timer_set'

        else:  # error
            logger.error(f"[{self.emulator_name}] ❌ Ошибка автоускорения Лорда")
            timer_val = remaining or initial_timer
            if timer_val and timer_val > 0:
                timer_finish = datetime.now() + timedelta(seconds=timer_val)
                self.db.set_building_upgrading(
                    emulator_id, "Лорд", None,
                    timer_finish, builder_slot,
                    actual_level=lord_level
                )
            return 'timer_set'

    def _handle_prime_time(self):
        """
        Проверить и выполнить drain ускорений строительства в ДС.

        Вызывается ПОСЛЕ основного цикла строительства (все строители заняты).
        Бот находится в поместье.

        ✅ FIX #4: Пропускает если Лорд улучшается.
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        try:
            # ── 1. Проверяем включён ли prime_times ──
            active_funcs = self.session_state.get('_active_functions', [])
            if 'prime_times' not in active_funcs:
                return

            # ── ✅ FIX #4: Если Лорд улучшается — не запускать prime ──
            lord = self.db.get_building(emu_id, "Лорд", None)
            if lord and lord['status'] == 'upgrading':
                logger.debug(
                    f"[{emu_name}] Prime: Лорд улучшается, "
                    f"пропускаем building drain"
                )
                return

            # ── 2. Активный ДС? ──
            now = datetime.now()
            event = get_current_event(now)
            if event is None:
                return

            event_key = event['event_key']
            event_type = event['type']

            # ── 3. ДС уже завершён? ──
            ds = self.session_state.get('prime_times')
            if ds and ds.get('completed') and ds.get('event_key') == event_key:
                return

            prime_st = PrimeStorage()
            if prime_st.is_completed(emu_id, event_key):
                return

            # ── 4. Безопасно ли начинать? ──
            progress = prime_st.get_progress(emu_id, event_key)
            spent = float(progress['spent_minutes']) if progress else 0.0

            if spent <= 0 and not is_safe_to_start(now, min_minutes=5):
                return

            # ── 5. Инициализация session_state если нужно ──
            if ds is None or ds.get('event_key') != event_key:
                ds = self._init_prime_session(event, prime_st)
                if ds is None:
                    return

            # ── 6. Проверяем что drain_type = building ──
            if ds.get('skip_reason') or ds.get('completed'):
                return

            if ds['drain_type'] != 'building':
                return

            # ── 7. Цикл drain ──
            logger.info(
                f"[{emu_name}] 🎯 Prime Time (building): "
                f"target={ds['target_minutes']} мин, "
                f"spent={ds['spent_minutes']:.0f} мин"
            )

            self._drain_building_in_prime(ds, event, prime_st)

        except Exception as e:
            logger.error(
                f"[{emu_name}] ❌ Ошибка в _handle_prime_time: {e}"
            )

    def _init_prime_session(
            self, event: dict, prime_st: PrimeStorage
    ) -> dict | None:
        """
        Инициализировать session_state['prime_times'] для точки A.

        Парсит очки ДС, выбирает drain_type, считает target_minutes.

        Returns:
            dict (session_state['prime_times']) или None при ошибке
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        event_key = event['event_key']
        event_type = event['type']
        ppm = event['points_per_min']

        # Инвентарь
        bp_storage = BackpackStorage()
        inventory = bp_storage.get_inventory(emu_id)
        if not inventory:
            logger.debug(f"[{emu_name}] Prime: нет данных ускорений")
            return None

        # Есть ли здания для строительства
        has_buildings = self.db.has_buildings_to_upgrade(emu_id)

        # Выбор drain_type
        drain_type, total_hours = choose_drain_type(
            inventory, event_type, has_buildings
        )
        if drain_type is None:
            logger.debug(f"[{emu_name}] Prime: не хватает ускорений")
            self._set_prime_skip(event_key, 'not_enough_speedups', prime_st)
            return self.session_state.get('prime_times')

        # Парсим очки ДС
        ds_points = parse_ds_points(self.emulator)
        if ds_points is None:
            logger.warning(f"[{emu_name}] Prime: не удалось спарсить очки ДС")
            from utils.function_freeze_manager import function_freeze_manager
            function_freeze_manager.freeze(
                emu_id, 'prime_times', hours=1,
                reason="Ошибка парсинга очков ДС",
            )
            return None

        # Target minutes
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
                self._set_prime_skip(event_key, '>65h', prime_st)
                return self.session_state.get('prime_times')

        if target_min <= 0:
            self._set_prime_completed(event_key, prime_st)
            return self.session_state.get('prime_times')

        # Восстановление из ds_progress
        progress = prime_st.get_progress(emu_id, event_key)
        spent = 0.0
        if progress and progress['status'] == 'in_progress':
            spent = float(progress['spent_minutes'])

        # Формируем session_state
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

        prime_st.save_progress(
            emu_id, event_key, target_min,
            int(spent), target_shell, 'in_progress',
        )

        logger.info(
            f"[{emu_name}] Prime init: drain={drain_type}, "
            f"target={target_min} мин (shell {target_shell})"
        )
        return ds

    def _drain_building_in_prime(
        self, ds: dict, event: dict, prime_st: PrimeStorage
):
        """
        Цикл drain строительных ускорений для ДС.

        Бот в поместье. Для каждой итерации:
        1. Найти здание с максимальным таймером
        2. Если нет — поставить новое здание на улучшение
        3. NavigationPanel → здание → "Ускорить" → окно ускорений
        4. drain_speedups()
        5. Обновить прогресс
        6. Если здание достроилось → ставим следующее → continue
        7. Если набрали очки → break
        ✅ FIX #3: Передаёт timers в calculate_plan
        ✅ FIX #8: continue вместо break при отсутствии speedup_icon
        ✅ FIX #2: Полное освобождение строителя при завершении
        ✅ FIX #9: expected_level при навигации (переупорядочивание панели)
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        bp_storage = BackpackStorage()

        while ds['spent_minutes'] < ds['target_minutes']:
            # Проверяем время
            if not is_safe_to_start(min_minutes=5):
                if ds['spent_minutes'] <= 0:
                    logger.info(f"[{emu_name}] Prime: мало времени до конца ДС")
                    break

            # Найти здание с максимальным таймером
            building_info = self._find_best_building_for_drain(emu_id)

            # Нет зданий с таймером → попробовать поставить новое
            if building_info is None:
                logger.info(
                    f"[{emu_name}] Prime: нет зданий с таймерами, "
                    f"пробуем поставить новое..."
                )
                if self._start_next_building(emu_id):
                    time.sleep(1.0)
                    building_info = self._find_best_building_for_drain(emu_id)

                if building_info is None:
                    logger.warning(
                        f"[{emu_name}] Prime: не удалось поставить здание, "
                        f"выходим из drain"
                    )
                    break

            b_name = building_info['name']
            b_index = building_info.get('index')
            b_level = building_info.get('current_level')
            display = b_name + (f" #{b_index}" if b_index else "")

            logger.info(
                f"[{emu_name}] Prime: drain → {display} Lv.{b_level} "
                f"(таймер ~{building_info['timer_sec'] // 60} мин)"
            )

            # ✅ FIX #9: Навигация с expected_level
            nav_ok = self.panel.navigate_to_building(
                self.emulator, b_name, building_index=b_index,
                expected_level=b_level,
            )
            if not nav_ok:
                logger.error(
                    f"[{emu_name}] Prime: навигация к {display} не удалась"
                )
                self._reset_panel_state()
                break

            # Клик по зданию → иконки действий вокруг здания
            from utils.adb_controller import tap as adb_tap
            adb_tap(self.emulator, x=268, y=517)
            time.sleep(1.5)

            # Открыть окно ускорений
            if not self.upgrade._open_speedup_window(self.emulator):
                # ✅ FIX #8: continue вместо break
                logger.warning(
                    f"[{emu_name}] Prime: иконка ускорения не найдена у "
                    f"{display}, здание возможно уже завершено"
                )
                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                self._reset_panel_state()
                # Помечаем как завершённое (если нечего ускорять — значит готово)
                self._complete_building_after_drain(emu_id, b_name, b_index)
                time.sleep(0.5)
                continue  # ← пробуем следующее здание

            # ── Рассчитать план НА ЭТО ЗДАНИЕ (не на весь ДС) ──
            remaining_ds_min = int(ds['target_minutes'] - ds['spent_minutes'])
            building_timer_min = max(1, building_info['timer_sec'] // 60)
            batch_target = min(remaining_ds_min, building_timer_min)

            logger.info(
                f"[{emu_name}] Prime пачка: "
                f"таймер здания={building_timer_min}мин, "
                f"осталось ДС={remaining_ds_min}мин, "
                f"batch={batch_target}мин"
            )

            inventory = bp_storage.get_inventory(emu_id)
            has_buildings = self.db.has_buildings_to_upgrade(emu_id)

            # ✅ FIX #3: Передаём timers
            timers = {'building_1': building_info['timer_sec']}

            plan = calculate_plan(
                inventory=inventory,
                target_minutes=batch_target,
                event_type=ds['event_type'],
                drain_type='building',
                has_buildings=has_buildings,
                target_shell=ds['target_shell'],
                skip_threshold=True,
                timers=timers,  # ← FIX #3
            )

            if plan.is_skip:
                logger.info(
                    f"[{emu_name}] Prime: план пустой — {plan.skip_reason}"
                )
                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                self._reset_panel_state()
                break

            # Drain!
            result = drain_speedups(
                self.emulator, plan, 'building', self.session_state
            )

            # Обновляем прогресс
            ds['spent_minutes'] += result.minutes_spent
            prime_st.add_spent_minutes(
                emu_id, event['event_key'], int(result.minutes_spent)
            )

            logger.info(
                f"[{emu_name}] Prime: +{result.minutes_spent:.0f} мин, "
                f"итого {ds['spent_minutes']:.0f}/{ds['target_minutes']}"
            )

            self._reset_panel_state()

            if result.building_completed:
                # ✅ FIX #2: Полное обновление (здание + строитель)
                self._complete_building_after_drain(emu_id, b_name, b_index)

                # Ставим следующее здание на улучшение (если есть)
                if not self._start_next_building(emu_id):
                    logger.info(
                        f"[{emu_name}] Prime: нет зданий для "
                        f"следующего улучшения"
                    )
                    break

                time.sleep(1.0)
                continue

            # Не достроилось → закрываем окно ускорений
            press_key(self.emulator, "ESC")
            time.sleep(0.5)
            break

        # Финализация
        if ds['spent_minutes'] >= ds['target_minutes']:
            self._set_prime_completed(event['event_key'], prime_st)
        else:
            logger.info(
                f"[{emu_name}] Prime: итого "
                f"{ds['spent_minutes']:.0f}/{ds['target_minutes']} мин"
            )

    def _find_best_building_for_drain(self, emu_id: int) -> dict | None:
        """
        Найти здание с максимальным оставшимся таймером.

        ✅ FIX #4: Исключает Лорда (требует спец. обработку:
        перезапуск игры после завершения).
        ✅ FIX #9: Возвращает current_level для navigate_to_building

        Returns:
            {'name': str, 'index': int|None, 'timer_sec': int}
            или None
        """
        now = datetime.now()
        best = None
        best_remaining = 0

        try:
            with self.db.db_lock:
                cursor = self.db.conn.cursor()
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
            logger.error(f"Ошибка _find_best_building_for_drain: {e}")

        return best

    def _complete_building_after_drain(
            self, emu_id: int, building_name: str, building_index: int | None
    ):
        """
        Обновить БД после того как drain завершил строительство.

        Здание достроилось через ускорения:
        - level += 1
        - status = idle
        - ✅ FIX: освобождаем строителя (builders.is_busy = 0)
        """
        try:
            building = self.db.get_building(emu_id, building_name, building_index)
            if building is None:
                return

            building_id = building['id']
            new_level = building.get('upgrading_to_level') or (building['current_level'] + 1)

            # 1. Обновляем здание (status=idle, timer=NULL)
            self.db.update_building_level(
                emu_id, building_name, building_index, new_level
            )

            # 2. ✅ FIX #2: Освобождаем строителя по building_id
            with self.db.db_lock:
                cursor = self.db.conn.cursor()
                cursor.execute("""
                        UPDATE builders
                        SET is_busy = 0, building_id = NULL, finish_time = NULL
                        WHERE emulator_id = ? AND building_id = ?
                    """, (emu_id, building_id))
                self.db.conn.commit()
                if cursor.rowcount > 0:
                    logger.info(
                        f"[{self.emulator_name}] 🔓 Строитель освобождён "
                        f"(building_id={building_id})"
                    )

            logger.success(
                f"[{self.emulator_name}] 🏗️ Prime: {building_name} "
                f"достроено → Lv.{new_level}"
            )
        except Exception as e:
            logger.error(f"Ошибка _complete_building_after_drain: {e}")

    def _start_next_building(self, emu_id: int) -> bool:
        """
        Поставить следующее здание на улучшение (для продолжения drain).

        Используется внутри prime time drain когда текущее здание
        достроилось и нужно поставить новое чтобы продолжить слив ускорений.

        Returns:
            True если здание поставлено (навигация + upgrade_building)
        """
        free_builder = self.db.get_free_builder(emu_id)
        if free_builder is None:
            return False

        next_building = self.db.get_next_building_to_upgrade(
            self.emulator, auto_scan=False
        )
        if not next_building:
            return False

        b_name = next_building['name']
        b_index = next_building.get('index')
        action = next_building.get('action', 'upgrade')

        if action == 'build':
            # Постройка — слишком сложно для inline prime,
            # оставляем для основного цикла
            return False

        # Навигация
        success = self.panel.navigate_to_building(
            self.emulator, b_name, building_index=b_index,
            expected_level=next_building['current_level'],
        )
        if not success:
            self._reset_panel_state()
            return False

        detected_level = self.panel.last_detected_level

        # Улучшение
        upgrade_ok, timer_sec = self.upgrade.upgrade_building(
            self.emulator, building_name=b_name, building_index=b_index
        )

        self._reset_panel_state()

        if upgrade_ok and timer_sec and timer_sec > 0:
            timer_finish = datetime.now() + timedelta(seconds=timer_sec)
            self.db.set_building_upgrading(
                emu_id, b_name, b_index,
                timer_finish, free_builder,
                actual_level=detected_level,
            )
            display = b_name + (f" #{b_index}" if b_index else "")
            logger.success(
                f"[{self.emulator_name}] Prime: {display} "
                f"поставлено на улучшение ({self._format_time(timer_sec)})"
            )
            return True

        elif upgrade_ok and (timer_sec == 0 or timer_sec is None):
            # Мгновенное улучшение
            new_level = (detected_level or next_building['current_level']) + 1
            self.db.update_building_level(emu_id, b_name, b_index, new_level)
            return True

        return False

    def _reset_panel_state(self):
        """Сбросить состояние навигационной панели."""
        try:
            self.panel.nav_state.close_panel()
        except Exception:
            pass

    # ── Prime helpers (статус) ──

    def _set_prime_completed(self, event_key: str, prime_st: PrimeStorage):
        """Пометить ДС как завершённый."""
        emu_id = self.emulator.get('id')
        ds = self.session_state.get('prime_times', {})
        ds['completed'] = True
        ds['event_key'] = event_key
        self.session_state['prime_times'] = ds
        prime_st.mark_completed(emu_id, event_key)
        logger.success(f"[{self.emulator_name}] 🎉 Prime: ДС {event_key} завершён!")

    def _set_prime_skip(self, event_key: str, reason: str, prime_st: PrimeStorage):
        """Пометить ДС как пропущенный."""
        emu_id = self.emulator.get('id')
        ds = self.session_state.get('prime_times', {})
        ds['event_key'] = event_key
        ds['skip_reason'] = reason
        ds['completed'] = False
        self.session_state['prime_times'] = ds
        prime_st.mark_skipped(emu_id, event_key, reason)

    def _lord_instant_finish(self, emulator_id: int, old_level: int,
                            expected_new: int) -> str:
        """
        Обработка мгновенного улучшения Лорда.

        1. Обновить уровень в БД
        2. Закрыть игру (force-stop)
        3. Перезапустить игру
        4. Верифицировать уровень в панели навигации
        ✅ FIX #7: Освобождает строителя после завершения.
        """
        logger.success(f"[{self.emulator_name}] 👑🎉 Лорд мгновенно! "
                       f"Lv.{old_level} → Lv.{expected_new}")

        # Предварительно обновляем БД
        self.db.update_building_level(emulator_id, "Лорд", None, expected_new)

        # ✅ FIX #7: Освобождаем строителя Лорда
        lord = self.db.get_building(emulator_id, "Лорд", None)
        if lord:
            with self.db.db_lock:
                cursor = self.db.conn.cursor()
                cursor.execute("""
                        UPDATE builders
                        SET is_busy = 0, building_id = NULL, finish_time = NULL
                        WHERE emulator_id = ? AND building_id = ?
                    """, (emulator_id, lord['id']))
                self.db.conn.commit()
                if cursor.rowcount > 0:
                    logger.info(
                        f"[{self.emulator_name}] 🔓 Строитель Лорда освобождён"
                    )

        # Перезапуск игры (всплывающие окна не закрываются ESC)
        logger.info(f"[{self.emulator_name}] 🔄 Перезапуск игры...")
        if not self._restart_game_only():
            logger.error(f"[{self.emulator_name}] ❌ Не удалось перезапустить игру")
            return 'upgraded'

        # Верификация уровня
        logger.info(f"[{self.emulator_name}] 🔍 Верификация уровня Лорда...")
        verify_ok = self.panel.navigate_to_building(
            self.emulator, "Лорд",
            building_index=None,
            expected_level=expected_new
        )

        if verify_ok:
            actual = self.panel.last_detected_level
            if actual and actual != expected_new:
                logger.error(
                    f"[{self.emulator_name}] ❌ РАСХОЖДЕНИЕ! "
                    f"Ожидали: {expected_new}, Факт: {actual}"
                )
                self.db.update_building_level(emulator_id, "Лорд", None, actual)
                if actual < expected_new:
                    logger.critical(
                        f"[{self.emulator_name}] 🚨 Уровень НИЖЕ ожидаемого: "
                        f"{actual} < {expected_new}"
                    )
            else:
                logger.success(f"[{self.emulator_name}] ✅ Верификация OK: "
                               f"Лорд Lv.{expected_new}")

        self._reset_panel_state()
        return 'upgraded'

    def _restart_game_only(self) -> bool:
        """
        Закрыть и перезапустить игру БЕЗ перезапуска эмулятора.
        Используется после мгновенного улучшения Лорда.
        """
        package = "com.allstarunion.beastlord"

        logger.info(f"[{self.emulator_name}] 🔄 force-stop игры...")
        adb_address = get_adb_device(self.emulator['port'])
        kill_cmd = f"adb -s {adb_address} shell am force-stop {package}"
        result = execute_command(kill_cmd)
        logger.debug(f"[{self.emulator_name}] force-stop: {result.strip()[:100]}")

        time.sleep(3)

        logger.info(f"[{self.emulator_name}] 🚀 Запуск игры...")
        launcher = GameLauncher(self.emulator)
        if not launcher.launch_and_wait():
            logger.error(f"[{self.emulator_name}] ❌ Игра не запустилась")
            return False

        logger.success(f"[{self.emulator_name}] ✅ Игра перезапущена")
        return True

    def _format_time(self, seconds: int) -> str:
        """Форматировать секунды в читаемый вид"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours}ч {minutes}м {secs}с"
        elif minutes > 0:
            return f"{minutes}м {secs}с"
        else:
            return f"{secs}с"