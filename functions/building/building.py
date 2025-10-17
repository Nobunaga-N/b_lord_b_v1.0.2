"""
Главный класс функции строительства
Объединяет NavigationPanel, BuildingUpgrade, BuildingDatabase

Версия: 1.0
Дата создания: 2025-01-17
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from functions.base_function import BaseFunction
from functions.building.navigation_panel import NavigationPanel
from functions.building.building_upgrade import BuildingUpgrade
from functions.building.building_database import BuildingDatabase
from utils.logger import logger


class BuildingFunction(BaseFunction):
    """
    Главная функция строительства

    Процесс:
    1. Проверить свободных строителей
    2. Определить следующее здание (BuildingDatabase)
    3. Перейти к зданию (NavigationPanel)
    4. Улучшить здание (BuildingUpgrade)
    5. Обновить БД
    6. Повторить пока есть свободные строители
    """

    def __init__(self, emulator):
        """Инициализация функции строительства"""
        super().__init__(emulator)
        self.name = "BuildingFunction"

        # Инициализация компонентов
        self.panel = NavigationPanel()
        self.upgrade = BuildingUpgrade()
        self.db = BuildingDatabase()

        logger.info(f"[{self.emulator_name}] ✅ BuildingFunction инициализирована")

    def can_execute(self) -> bool:
        """
        Проверить можно ли выполнить строительство

        Условия:
        1. Эмулятор не заморожен (нехватка ресурсов)
        2. Есть свободные строители
        3. Есть здания для прокачки

        Returns:
            True если можно строить
        """
        emulator_id = self.emulator.get('id', 0)

        # ПРОВЕРКА 0: Инициализация строителей (первый запуск)
        # Проверяем есть ли записи в таблице builders для этого эмулятора
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM builders WHERE emulator_id = ?
            """, (emulator_id,))
            builders_count = cursor.fetchone()[0]

            if builders_count == 0:
                logger.info(f"[{self.emulator_name}] 🔍 Первый запуск: определяю количество строителей через OCR...")

                # Распознаем строителей через OCR (передаем полный объект эмулятора)
                busy, total = self.db.detect_builders_count(self.emulator)

                logger.info(f"[{self.emulator_name}] 🔨 Обнаружено строителей: {busy}/{total}")

                # Инициализируем строителей в БД
                self.db.init_emulator_builders(emulator_id, slots=total)

                # Если есть занятые строители - отмечаем их в БД
                if busy > 0:
                    logger.warning(f"[{self.emulator_name}] ⚠️ {busy} строителей уже заняты, но таймеры неизвестны")
                    # Можно добавить логику для парсинга таймеров через панель навигации
                    # Пока просто отмечаем их как занятых без таймера
                    for slot in range(1, busy + 1):
                        cursor.execute("""
                            UPDATE builders 
                            SET is_busy = 1 
                            WHERE emulator_id = ? AND builder_slot = ?
                        """, (emulator_id, slot))
                    self.db.conn.commit()

                logger.success(f"[{self.emulator_name}] ✅ Строители инициализированы: {total - busy} свободных")

        except Exception as e:
            logger.error(f"[{self.emulator_name}] ❌ Ошибка при инициализации строителей: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

        # ПРОВЕРКА 1: Заморозка эмулятора
        if self.db.is_emulator_frozen(emulator_id):
            freeze_info = self.db.get_freeze_info(emulator_id)
            logger.debug(f"[{self.emulator_name}] ❄️ Эмулятор заморожен до {freeze_info['freeze_until']}")
            return False

        # ПРОВЕРКА 2: Свободные строители
        free_builders = self.db.get_free_builders_count(emulator_id)
        if free_builders == 0:
            logger.debug(f"[{self.emulator_name}] 👷 Нет свободных строителей")
            return False

        # ПРОВЕРКА 3: Есть ли что строить
        next_building = self.db.get_next_building_to_upgrade(emulator_id)
        if not next_building:
            logger.debug(f"[{self.emulator_name}] 🎯 Все здания достигли целевого уровня")
            return False

        logger.debug(f"[{self.emulator_name}] ✅ Можно строить: {free_builders} строителей, "
                     f"следующее здание: {next_building['name']}")
        return True

    def execute(self) -> bool:
        """
        Выполнить цикл строительства

        Процесс:
        1. Пока есть свободные строители
        2. Определить следующее здание
        3. Перейти и улучшить
        4. Обновить БД
        5. Повторить

        Returns:
            True если хотя бы одно здание улучшено
        """
        emulator_id = self.emulator.get('id', 0)

        logger.info(f"[{self.emulator_name}] 🏗️ Начало цикла строительства")

        upgraded_count = 0

        # Цикл пока есть свободные строители
        while True:
            # Проверяем условия
            if not self.can_execute():
                break

            # Получаем следующее здание
            next_building = self.db.get_next_building_to_upgrade(emulator_id)
            if not next_building:
                break

            building_name = next_building['name']
            building_index = next_building.get('index')
            current_level = next_building['current_level']
            target_level = next_building['target_level']

            display_name = building_name
            if building_index is not None:
                display_name += f" #{building_index}"

            logger.info(f"[{self.emulator_name}] 🎯 Следующее здание: {display_name} "
                       f"(Lv.{current_level} → Lv.{target_level})")

            # ШАГ 1: Перейти к зданию
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
                        emulator_id, building_name, new_level, building_index
                    )

                    # Проверяем нужно ли добавить 4-й слот строителя
                    if building_name == "Жилище Лемуров IV" and new_level >= 1:
                        self.db.add_builder_slot(emulator_id)

                else:
                    # Обычное улучшение с таймером
                    timer_finish = datetime.now() + timedelta(seconds=timer_seconds)

                    # Получаем свободный слот строителя
                    builder_slot = self.db.get_free_builder_slot(emulator_id)
                    if builder_slot is None:
                        logger.error(f"[{self.emulator_name}] ❌ Нет свободных строителей в БД")
                        break

                    # Обновляем БД
                    self.db.set_building_upgrading(
                        emulator_id, building_name, building_index,
                        timer_finish, builder_slot
                    )

                    logger.success(f"[{self.emulator_name}] ✅ Улучшение началось: {display_name}")
                    logger.info(f"[{self.emulator_name}] ⏱️ Завершится: {timer_finish.strftime('%H:%M:%S')}")

                upgraded_count += 1

            else:
                # Нехватка ресурсов - заморозка
                logger.warning(f"[{self.emulator_name}] ❄️ Недостаточно ресурсов для {display_name}")

                freeze_until = datetime.now() + timedelta(hours=6)
                self.db.freeze_emulator(
                    emulator_id,
                    freeze_until,
                    f"Нехватка ресурсов для {display_name}"
                )

                logger.info(f"[{self.emulator_name}] ❄️ Эмулятор заморожен до {freeze_until.strftime('%H:%M:%S')}")
                break

            # Пауза между улучшениями
            time.sleep(2)

        # Итоги
        if upgraded_count > 0:
            logger.success(f"[{self.emulator_name}] ✅ Улучшено зданий: {upgraded_count}")
            return True
        else:
            logger.info(f"[{self.emulator_name}] ℹ️ Строительство не выполнено")
            return False


# Экспорт
__all__ = ['BuildingFunction']