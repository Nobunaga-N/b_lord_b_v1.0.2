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

    def __init__(self, emulator):
        """Инициализация функции строительства"""
        super().__init__(emulator)
        self.name = "BuildingFunction"

        # Инициализация компонентов
        self.panel = NavigationPanel()
        self.upgrade = BuildingUpgrade()
        self.construction = BuildingConstruction()
        self.db = BuildingDatabase()

        logger.info(f"[{self.emulator_name}] ✅ BuildingFunction инициализирована")

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

        # Закрываем панель навигации если она открыта
        press_key(self.emulator, "ESC")
        time.sleep(0.5)

        success = self.db.perform_initial_scan(self.emulator)

        if not success:
            logger.warning(f"[{self.emulator_name}] ⚠️ Первичное сканирование завершено с ошибками")
            # Не возвращаем False - можно продолжать работу

        logger.success(f"[{self.emulator_name}] ✅ Инициализация завершена")
        return True

    def can_execute(self) -> bool:
        """
        Проверить можно ли выполнить строительство

        Условия:
        1. Инициализация при первом запуске
        2. Эмулятор не заморожен (нехватка ресурсов)
        3. Есть свободные строители
        4. Есть здания для прокачки

        Returns:
            True если можно строить
        """
        emulator_id = self.emulator.get('id', 0)

        # ПРОВЕРКА 0: Инициализация при первом запуске
        if not self._first_time_initialization():
            logger.error(f"[{self.emulator_name}] ❌ Ошибка инициализации")
            return False

        # ПРОВЕРКА 1: Заморозка эмулятора
        if self.db.is_emulator_frozen(emulator_id):
            logger.debug(f"[{self.emulator_name}] ❄️ Эмулятор заморожен (нехватка ресурсов)")
            return False

        # ПРОВЕРКА 2: Свободные строители
        free_builder = self.db.get_free_builder(emulator_id)
        if free_builder is None:
            logger.debug(f"[{self.emulator_name}] 👷 Нет свободных строителей")
            return False

        # ПРОВЕРКА 3: Есть ли что строить (с автосканированием)
        next_building = self.db.get_next_building_to_upgrade(self.emulator, auto_scan=True)
        if not next_building:
            logger.debug(f"[{self.emulator_name}] 🎯 Все здания достигли целевого уровня")
            return False

        logger.debug(f"[{self.emulator_name}] ✅ Можно строить: следующее здание - {next_building['name']}")
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

        Returns:
            True если хотя бы одно здание улучшено/построено
        """
        emulator_id = self.emulator.get('id', 0)

        logger.info(f"[{self.emulator_name}] 🏗️ Начало цикла строительства")

        completed_count = self.db.check_and_update_completed_buildings(emulator_id)
        if completed_count > 0:
            logger.info(f"[{self.emulator_name}] 🎉 Завершено построек с прошлого цикла: {completed_count}")

        upgraded_count = 0
        constructed_count = 0

        # Цикл пока есть свободные строители
        while True:
            # Проверяем условия (без инициализации - она уже выполнена)
            if self.db.is_emulator_frozen(emulator_id):
                logger.info(f"[{self.emulator_name}] ❄️ Эмулятор заморожен")
                break

            free_builder = self.db.get_free_builder(emulator_id)
            if free_builder is None:
                logger.info(f"[{self.emulator_name}] 👷 Нет свободных строителей")
                break

            # Получаем следующее здание (с автосканированием)
            next_building = self.db.get_next_building_to_upgrade(self.emulator, auto_scan=True)
            if not next_building:
                logger.info(f"[{self.emulator_name}] ✅ Все здания достигли целевого уровня")
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

            # ШАГ 1: Перейти к зданию (для upgrade) или открыть меню постройки (для construct)
            if action == 'construct':
                # ПОСТРОЙКА НОВОГО ЗДАНИЯ
                logger.info(f"[{self.emulator_name}] 🏗️ Постройка нового здания: {display_name}")

                # Закрываем панель навигации если открыта
                press_key(self.emulator, "ESC")
                time.sleep(0.5)

                # Строим здание через BuildingConstruction
                success, timer_seconds = self.construction.construct_building(
                    self.emulator, building_name, building_index
                )

                if success:
                    if timer_seconds == 0:
                        # Быстрое завершение (помощь альянса)
                        logger.success(f"[{self.emulator_name}] 🚀 Мгновенная постройка: {display_name}")

                        # Обновляем уровень сразу на 1
                        self.db.update_building_level(
                            emulator_id, building_name, building_index, 1
                        )

                        constructed_count += 1
                    else:
                        # Обычная постройка с таймером
                        timer_finish = datetime.now() + timedelta(seconds=timer_seconds)

                        # Получаем свободный слот строителя
                        builder_slot = self.db.get_free_builder(emulator_id)
                        if builder_slot is None:
                            logger.error(f"[{self.emulator_name}] ❌ Нет свободных строителей в БД")
                            break

                        # Обновляем БД - здание строится
                        self.db.set_building_constructed(
                            emulator_id, building_name, building_index,
                            timer_finish, builder_slot
                        )

                        logger.success(f"[{self.emulator_name}] ✅ Постройка началась: {display_name}")
                        logger.info(f"[{self.emulator_name}] ⏱️ Таймер: {self._format_time(timer_seconds)}")

                        constructed_count += 1
                else:
                    # Не удалось построить (нехватка ресурсов)
                    logger.warning(f"[{self.emulator_name}] ❌ Не удалось построить: {display_name}")

                    # Замораживаем эмулятор
                    self.db.freeze_emulator(emulator_id, hours=6, reason="Нехватка ресурсов (постройка)")
                    break

            else:
                # УЛУЧШЕНИЕ СУЩЕСТВУЮЩЕГО ЗДАНИЯ
                if not self.panel.open_navigation_panel(self.emulator):
                    logger.error(f"[{self.emulator_name}] ❌ Не удалось открыть панель навигации")
                    break

                if not self.panel.navigate_to_building(self.emulator, building_name):
                    logger.error(f"[{self.emulator_name}] ❌ Не удалось перейти к зданию")
                    break

                time.sleep(1.5)

                # ШАГ 2: Улучшить здание
                success, timer_seconds = self.upgrade.upgrade_building(
                    self.emulator, building_name, building_index
                )

                # ШАГ 3: Обработка результата
                if success:
                    if timer_seconds == 0:
                        # Быстрое завершение (помощь альянса)
                        logger.success(f"[{self.emulator_name}] 🚀 Мгновенное улучшение: {display_name}")

                        # Обновляем уровень сразу
                        new_level = current_level + 1
                        self.db.update_building_level(
                            emulator_id, building_name, building_index, new_level
                        )

                        # Проверяем нужно ли добавить 4-й слот строителя
                        if building_name == "Жилище Лемуров" and building_index == 4 and new_level >= 1:
                            self.db.initialize_builders(emulator_id, slots=4)
                            logger.success(f"[{self.emulator_name}] 🔨 Добавлен 4-й строитель!")

                        upgraded_count += 1

                    else:
                        # Обычное улучшение с таймером
                        timer_finish = datetime.now() + timedelta(seconds=timer_seconds)

                        # Получаем свободный слот строителя
                        builder_slot = self.db.get_free_builder(emulator_id)
                        if builder_slot is None:
                            logger.error(f"[{self.emulator_name}] ❌ Нет свободных строителей в БД")
                            break

                        # Обновляем БД
                        self.db.set_building_upgrading(
                            emulator_id, building_name, building_index,
                            timer_finish, builder_slot
                        )

                        logger.success(f"[{self.emulator_name}] ✅ Улучшение началось: {display_name}")
                        logger.info(f"[{self.emulator_name}] ⏱️ Таймер: {self._format_time(timer_seconds)}")

                        upgraded_count += 1

                else:
                    # Не удалось улучшить (нехватка ресурсов)
                    logger.warning(f"[{self.emulator_name}] ❌ Недостаточно ресурсов для: {display_name}")

                    # Замораживаем эмулятор
                    self.db.freeze_emulator(emulator_id, hours=6, reason="Нехватка ресурсов")
                    break

            # Пауза между зданиями
            time.sleep(2)

        # Итоги
        total = upgraded_count + constructed_count

        if total > 0:
            logger.success(f"[{self.emulator_name}] 🎉 Цикл строительства завершен!")
            logger.info(f"[{self.emulator_name}] 📊 Улучшено: {upgraded_count}, Построено: {constructed_count}")
            return True
        else:
            logger.info(f"[{self.emulator_name}] ℹ️ Ничего не построено в этом цикле")
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