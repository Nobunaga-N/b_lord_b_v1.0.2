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
        1. Нет записей в БД → datetime.min (новый эмулятор, первичное сканирование)
        2. Эмулятор заморожен → время разморозки
        3. Есть свободный строитель + есть что строить → datetime.now() (нужен сейчас)
        4. Есть свободный строитель, но строить нечего → None
        5. Все строители заняты + есть что строить → время ближайшего освобождения
        6. Все строители заняты + строить нечего → None

        Returns:
            datetime — когда нужен эмулятор
            None — эмулятор не нужен для строительства

        ИСПРАВЛЕНО: Проверяет function_freeze_manager (in-memory)
        в первую очередь, ДО проверок через БД.
        """
        # ===== НОВОЕ: Проверка in-memory заморозки =====
        from utils.function_freeze_manager import function_freeze_manager

        # Единая проверка заморозки
        if function_freeze_manager.is_frozen(emulator_id, 'building'):
            unfreeze_at = function_freeze_manager.get_unfreeze_time(
                emulator_id, 'building'
            )
            if unfreeze_at:
                logger.debug(
                    f"[Emulator {emulator_id}] 🧊 building заморожена "
                    f"до {unfreeze_at.strftime('%H:%M:%S')}"
                )
                return unfreeze_at
            return None

        db = BuildingDatabase()

        try:
            # 1. Новый эмулятор?
            if not db.has_buildings(emulator_id):
                return datetime.min

            # 2. УБРАНО: db.is_emulator_frozen() — больше не нужно!
            #    Менеджер уже проверен выше.

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
            logger.error(f"[Emulator {emulator_id}] Ошибка в "
                         f"BuildingFunction.get_next_event_time: {e}")
            return None

    def _first_time_initialization(self) -> bool:
        """
        Инициализация при первом запуске эмулятора

        1. Проверить есть ли записи в БД
        2. Если нет - создать записи для всех зданий
        3. Определить количество строителей через OCR
        4. Выполнить первичное сканирование уровней

        Returns:
            bool: True если инициализация успешна
        """
        emulator_id = self.emulator.get('id', 0)

        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM buildings WHERE emulator_id = ?
        """, (emulator_id,))

        buildings_count = cursor.fetchone()[0]

        # Если записи уже есть - инициализация не нужна
        if buildings_count > 0:
            logger.debug(f"[{self.emulator_name}] БД уже инициализирована ({buildings_count} зданий)")
            return True

        logger.info(f"[{self.emulator_name}] 🆕 ПЕРВЫЙ ЗАПУСК - Начало инициализации...")

        # ШАГ 1: Определить количество строителей через OCR
        logger.info(f"[{self.emulator_name}] 🔍 Определение количества строителей...")
        busy, total = self.db.detect_builders_count(self.emulator)

        logger.info(f"[{self.emulator_name}] 🔨 Строители: {busy}/{total}")

        # ШАГ 2: Создать записи для всех зданий
        logger.info(f"[{self.emulator_name}] 📋 Создание записей в БД...")
        success = self.db.initialize_buildings_for_emulator(emulator_id, total)

        if not success:
            logger.error(f"[{self.emulator_name}] ❌ Ошибка инициализации БД")
            return False

        # ШАГ 3: Выполнить первичное сканирование
        logger.info(f"[{self.emulator_name}] 🔍 Запуск первичного сканирования...")

        success = self.db.perform_initial_scan(self.emulator)

        if not success:
            logger.warning(f"[{self.emulator_name}] ⚠️ Первичное сканирование завершено с ошибками")
            # Не возвращаем False - можно продолжать работу

        logger.success(f"[{self.emulator_name}] ✅ Инициализация завершена")
        return True

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

                # ✅ ИСПРАВЛЕНО: убран лишний emulator_id, распаковка tuple
                upgrade_success, timer_seconds = self.upgrade.upgrade_building(
                    self.emulator,
                    building_name=building_name,
                    building_index=building_index
                )

                if upgrade_success and timer_seconds and timer_seconds > 0:
                    # Улучшение началось с таймером
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
                    # Мгновенное завершение (помощь альянса)
                    new_level = (detected_level or current_level) + 1
                    self.db.update_building_level(
                        emulator_id, building_name, building_index, new_level
                    )
                    upgraded_count += 1
                    logger.success(f"[{self.emulator_name}] ⚡ {display_name} "
                                   f"мгновенное улучшение → Lv.{new_level}")

                else:
                    # Неудача (нехватка ресурсов или ошибка)
                    self.db.freeze_emulator(emulator_id, hours=6,
                                            reason="Нехватка ресурсов")
                    logger.warning(f"[{self.emulator_name}] ❄️ Заморозка на 6 часов")
                    resources_frozen = True
                    break

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