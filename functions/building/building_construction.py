"""
Модуль постройки новых зданий
Обрабатывает процесс постройки через меню лопаты

Версия: 1.3 (ФИНАЛЬНАЯ)
Дата обновления: 2025-01-17
Изменения:
- ИСПРАВЛЕНО: Правильные параметры для swipe()
- ДОБАВЛЕНО: Шаг с молоточком и кнопкой "Построить" после "Подтвердить"
- ИСПРАВЛЕНО: Использование правильного метода для проверки здания
"""

import os
import time
from typing import Dict, Optional
from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image
from utils.logger import logger

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BuildingConstruction:
    """Класс для постройки новых зданий"""

    # Координаты
    SHOVEL_ICON = (497, 768)
    CONFIRM_BUTTON = (327, 552)
    HAMMER_ICON = (268, 517)  # Молоточек на месте здания
    BUILD_BUTTON = (327, 552)  # Кнопка "Построить" (такая же координата как "Подтвердить")

    # Свайпы для поиска зданий
    SWIPE_START_X = 533
    SWIPE_START_Y = 846
    SWIPE_END_X = 3
    SWIPE_END_Y = 846
    MAX_SWIPES = 4

    # Шаблоны категорий
    CATEGORY_TEMPLATES = {
        "Популяция Стаи": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'categories', 'category_populyaciya_stai.png'),
        "Развитие": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'categories', 'category_razvitie.png'),
        "Фрукты": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'categories', 'category_frukty.png'),
        "Листья": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'categories', 'category_listya.png'),
        "Грунт": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'categories', 'category_grunt.png'),
        "Песок": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'categories', 'category_pesok.png'),
        "Битва": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'categories', 'category_bitva.png'),
    }

    # Fallback координаты категорий
    CATEGORY_COORDS = {
        "Популяция Стаи": (155, 400),
        "Развитие": (158, 515),
        "Фрукты": (155, 174),
        "Листья": (376, 174),
        "Грунт": (160, 291),
        "Песок": (160, 272),
        "Битва": (271, 513),
    }

    # Маппинг зданий к категориям
    BUILDING_TO_CATEGORY = {
        "Жилище Лемуров IV": "Развитие",
        "Центр Сбора II": "Битва",
        "Центр Сбора III": "Битва",
        "Склад Фруктов II": "Фрукты",
        "Склад Листьев II": "Листья",
        "Склад Грунта II": "Грунт",
        "Склад Песка II": "Песок",
        "Жилище Детенышей": "Популяция Стаи",
    }

    # Шаблоны зданий
    BUILDING_TEMPLATES = {
        "Жилище Лемуров IV": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'jiliche_lemurov_4.png'),
        "Центр Сбора II": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'centr_sbora_2.png'),
        "Центр Сбора III": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'centr_sbora_3.png'),
        "Склад Фруктов II": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'sklad_fruktov_2.png'),
        "Склад Листьев II": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'sklad_listev_2.png'),
        "Склад Грунта II": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'sklad_grunta_2.png'),
        "Склад Песка II": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'sklad_peska_2.png'),
        "Жилище Детенышей": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'jiliche_detenyshey_5.png'),
    }

    CONFIRM_BUTTON_TEMPLATE = os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'button_confirm.png')
    HAMMER_ICON_TEMPLATE = os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'hammer_icon.png')
    BUILD_BUTTON_TEMPLATE = os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'button_build.png')

    THRESHOLD_CATEGORY = 0.8
    THRESHOLD_BUILDING = 0.85
    THRESHOLD_BUTTON = 0.85
    THRESHOLD_HAMMER = 0.8
    THRESHOLD_BUILD = 0.85

    def __init__(self):
        """Инициализация модуля постройки"""
        # Проверяем шаблоны категорий
        for name, path in self.CATEGORY_TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "⚠️"
            logger.debug(f"{status} Шаблон категории '{name}': {path}")

        # Проверяем шаблоны зданий
        for name, path in self.BUILDING_TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "⚠️"
            logger.debug(f"{status} Шаблон здания '{name}': {path}")

        # Проверяем кнопки и иконки
        button_templates = {
            "Подтвердить": self.CONFIRM_BUTTON_TEMPLATE,
            "Молоточек": self.HAMMER_ICON_TEMPLATE,
            "Построить": self.BUILD_BUTTON_TEMPLATE
        }

        for name, path in button_templates.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "⚠️"
            logger.debug(f"{status} Шаблон '{name}': {path}")

        logger.info("✅ BuildingConstruction инициализирован")

    def construct_building(self, emulator: Dict, building_name: str, building_index: Optional[int] = None) -> bool:
        """ГЛАВНЫЙ МЕТОД - Построить новое здание"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        building_display = f"{building_name}" + (f" #{building_index}" if building_index else "")

        logger.info(f"[{emulator_name}] 🏗️ Начало постройки: {building_display}")

        if self._try_construct(emulator, building_name):
            logger.success(f"[{emulator_name}] ✅ Здание построено: {building_display}")
            return True

        logger.warning(f"[{emulator_name}] ⚠️ Первая попытка неудачна, повторяем...")
        time.sleep(2)

        if self._try_construct(emulator, building_name):
            logger.success(f"[{emulator_name}] ✅ Здание построено (попытка 2): {building_display}")
            return True

        logger.error(f"[{emulator_name}] ❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось построить {building_display}")
        return False

    def _try_construct(self, emulator: Dict, building_name: str) -> bool:
        """Одна попытка постройки здания"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ШАГ 1: Открыть меню постройки (лопата)
        if not self._open_construction_menu(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось открыть меню постройки")
            return False

        # ШАГ 2: Выбрать категорию
        category = self.BUILDING_TO_CATEGORY.get(building_name)
        if not category or not self._select_category(emulator, category):
            logger.error(f"[{emulator_name}] ❌ Не удалось выбрать категорию")
            return False

        # ШАГ 3: Найти и кликнуть по зданию
        if not self._find_and_click_building(emulator, building_name):
            logger.error(f"[{emulator_name}] ❌ Не удалось найти здание")
            press_key(emulator, "BACK")
            time.sleep(1)
            return False

        # ШАГ 4: Кликнуть "Подтвердить"
        if not self._click_confirm(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось кликнуть Подтвердить")
            press_key(emulator, "BACK")
            time.sleep(1)
            return False

        # ШАГ 5: НОВОЕ - Кликнуть молоточек и "Построить"
        if not self._click_hammer_and_build(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось завершить постройку через молоточек")
            return False

        # ШАГ 6: Проверить что здание построено
        if not self._verify_construction(emulator, building_name):
            logger.error(f"[{emulator_name}] ❌ Здание не появилось после постройки")
            return False

        return True

    def _open_construction_menu(self, emulator: Dict) -> bool:
        """Открыть меню постройки (клик лопаты)"""
        tap(emulator, x=self.SHOVEL_ICON[0], y=self.SHOVEL_ICON[1])
        time.sleep(2)
        return True

    def _select_category(self, emulator: Dict, category_name: str) -> bool:
        """Выбрать категорию здания"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        template_path = self.CATEGORY_TEMPLATES.get(category_name)
        if template_path and os.path.exists(template_path):
            result = find_image(emulator, template_path, threshold=self.THRESHOLD_CATEGORY)
            if result:
                center_x, center_y = result
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)
                return True

        coords = self.CATEGORY_COORDS.get(category_name)
        if coords:
            tap(emulator, x=coords[0], y=coords[1])
            time.sleep(1.5)
            return True

        return False

    def _find_and_click_building(self, emulator: Dict, building_name: str) -> bool:
        """Найти здание через свайпы + шаблоны"""
        template_path = self.BUILDING_TEMPLATES.get(building_name)
        if not template_path or not os.path.exists(template_path):
            return False

        for swipe_attempt in range(self.MAX_SWIPES + 1):
            if swipe_attempt > 0:
                # ИСПРАВЛЕНО: позиционные параметры для swipe()
                swipe(emulator,
                      self.SWIPE_START_X, self.SWIPE_START_Y,
                      self.SWIPE_END_X, self.SWIPE_END_Y,
                      300)
                time.sleep(1)

            result = find_image(emulator, template_path, threshold=self.THRESHOLD_BUILDING)
            if result:
                center_x, center_y = result
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)
                return True

        return False

    def _click_confirm(self, emulator: Dict) -> bool:
        """Кликнуть кнопку 'Подтвердить'"""
        if os.path.exists(self.CONFIRM_BUTTON_TEMPLATE):
            result = find_image(emulator, self.CONFIRM_BUTTON_TEMPLATE, threshold=self.THRESHOLD_BUTTON)
            if result:
                center_x, center_y = result
                tap(emulator, x=center_x, y=center_y)
                time.sleep(2)
                return True

        tap(emulator, x=self.CONFIRM_BUTTON[0], y=self.CONFIRM_BUTTON[1])
        time.sleep(2)
        return True

    def _click_hammer_and_build(self, emulator: Dict) -> bool:
        """
        НОВЫЙ МЕТОД: Кликнуть молоточек и кнопку 'Построить'

        Процесс:
        1. После 'Подтвердить' появляется место под здание с молоточком
        2. Ищем и кликаем молоточек (через шаблон)
        3. Открывается меню постройки
        4. Ищем и кликаем 'Построить' (через шаблон)
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ШАГ 1: Найти и кликнуть молоточек
        logger.debug(f"[{emulator_name}] Поиск молоточка...")

        if os.path.exists(self.HAMMER_ICON_TEMPLATE):
            result = find_image(emulator, self.HAMMER_ICON_TEMPLATE, threshold=self.THRESHOLD_HAMMER)

            if result:
                center_x, center_y = result
                logger.debug(f"[{emulator_name}] Молоточек найден через шаблон: ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)
            else:
                logger.warning(f"[{emulator_name}] ⚠️ Молоточек не найден через шаблон, используем fallback")
                tap(emulator, x=self.HAMMER_ICON[0], y=self.HAMMER_ICON[1])
                time.sleep(1.5)
        else:
            logger.warning(f"[{emulator_name}] ⚠️ Шаблон молоточка не найден, используем fallback координаты")
            tap(emulator, x=self.HAMMER_ICON[0], y=self.HAMMER_ICON[1])
            time.sleep(1.5)

        # ШАГ 2: Найти и кликнуть кнопку "Построить"
        logger.debug(f"[{emulator_name}] Поиск кнопки 'Построить'...")

        if os.path.exists(self.BUILD_BUTTON_TEMPLATE):
            result = find_image(emulator, self.BUILD_BUTTON_TEMPLATE, threshold=self.THRESHOLD_BUILD)

            if result:
                center_x, center_y = result
                logger.debug(f"[{emulator_name}] Кнопка 'Построить' найдена через шаблон: ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(2)
            else:
                logger.warning(f"[{emulator_name}] ⚠️ Кнопка 'Построить' не найдена через шаблон, используем fallback")
                tap(emulator, x=self.BUILD_BUTTON[0], y=self.BUILD_BUTTON[1])
                time.sleep(2)
        else:
            logger.warning(f"[{emulator_name}] ⚠️ Шаблон кнопки 'Построить' не найден, используем fallback координаты")
            tap(emulator, x=self.BUILD_BUTTON[0], y=self.BUILD_BUTTON[1])
            time.sleep(2)

        return True

    def _verify_construction(self, emulator: Dict, building_name: str) -> bool:
        """Проверить что здание построено через панель навигации"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Проверка постройки через панель навигации...")
        time.sleep(2)

        try:
            from functions.building.navigation_panel import NavigationPanel
            panel = NavigationPanel()

            # Открываем панель
            if not panel.open_navigation_panel(emulator):
                logger.warning(f"[{emulator_name}] ⚠️ Не удалось открыть панель навигации")
                return False

            # ИСПРАВЛЕНО: используем правильный метод navigate_to_building
            # который внутри парсит список и проверяет наличие здания
            success = panel.navigate_to_building(emulator, building_name)

            press_key(emulator, "BACK")  # Закрываем панель
            time.sleep(1)

            if success:
                logger.success(f"[{emulator_name}] ✅ Здание найдено в панели навигации: {building_name}")
                return True
            else:
                logger.error(f"[{emulator_name}] ❌ Здание {building_name} не найдено в панели навигации")
                return False

        except Exception as e:
            logger.error(f"[{emulator_name}] ❌ Ошибка при проверке через панель навигации: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False