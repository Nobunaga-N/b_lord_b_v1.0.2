"""
Модуль постройки новых зданий
Обрабатывает процесс постройки через меню лопаты

Версия: 1.0
Дата создания: 2025-01-17
"""

import os
import time
from typing import Dict, Optional, Tuple
from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.logger import logger

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BuildingConstruction:
    """
    Класс для постройки новых зданий

    Процесс:
    1. Открыть меню постройки (лопата)
    2. Выбрать категорию (шаблон → fallback координаты)
    3. Найти здание (свайпы + шаблоны)
    4. Кликнуть по зданию
    5. Кликнуть "Подтвердить"
    6. Проверить: кнопка исчезла + панель навигации
    7. Повторить при неудаче → критическая ошибка
    """

    # Координаты
    SHOVEL_ICON = (497, 768)
    CONFIRM_BUTTON = (327, 552)

    # Свайпы для поиска зданий
    SWIPE_START = (533, 846)
    SWIPE_END = (3, 846)
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
        "Жилище Детенышей": "Популяция Стаи",  # (5-е)
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

    # Шаблон кнопки "Подтвердить"
    CONFIRM_BUTTON_TEMPLATE = os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'button_confirm.png')

    # Пороги для поиска
    THRESHOLD_CATEGORY = 0.8
    THRESHOLD_BUILDING = 0.85
    THRESHOLD_BUTTON = 0.85

    def __init__(self):
        """Инициализация модуля постройки"""
        # Проверяем шаблоны
        for name, path in self.CATEGORY_TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "⚠️"
            logger.debug(f"{status} Шаблон категории '{name}': {path}")

        for name, path in self.BUILDING_TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "⚠️"
            logger.debug(f"{status} Шаблон здания '{name}': {path}")

        logger.info("✅ BuildingConstruction инициализирован")

    def construct_building(self, emulator: Dict, building_name: str,
                          building_index: Optional[int] = None) -> bool:
        """
        ГЛАВНЫЙ МЕТОД - Построить новое здание

        Args:
            emulator: объект эмулятора
            building_name: название здания для постройки
            building_index: индекс (для множественных зданий)

        Returns:
            True если постройка успешна
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        building_display = f"{building_name}"
        if building_index is not None:
            building_display += f" #{building_index}"

        logger.info(f"[{emulator_name}] 🏗️ Начало постройки: {building_display}")

        # Попытка 1: основная попытка
        if self._try_construct(emulator, building_name):
            logger.success(f"[{emulator_name}] ✅ Здание построено: {building_display}")
            return True

        logger.warning(f"[{emulator_name}] ⚠️ Первая попытка неудачна, повторяем...")
        time.sleep(2)

        # Попытка 2: повторная попытка
        if self._try_construct(emulator, building_name):
            logger.success(f"[{emulator_name}] ✅ Здание построено (попытка 2): {building_display}")
            return True

        # Обе попытки неудачны - критическая ошибка
        logger.error(f"[{emulator_name}] ❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось построить {building_display}")
        logger.error(f"[{emulator_name}] 📝 Необходимо залогировать в GUI!")
        # TODO: Интеграция с GUI для отображения критических ошибок
        return False

    def _try_construct(self, emulator: Dict, building_name: str) -> bool:
        """
        Одна попытка постройки здания

        Returns:
            True если постройка успешна
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ШАГ 1: Открыть меню постройки
        if not self._open_construction_menu(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось открыть меню постройки")
            return False

        # ШАГ 2: Выбрать категорию
        category = self.BUILDING_TO_CATEGORY.get(building_name)
        if not category:
            logger.error(f"[{emulator_name}] ❌ Неизвестная категория для {building_name}")
            return False

        if not self._select_category(emulator, category):
            logger.error(f"[{emulator_name}] ❌ Не удалось выбрать категорию {category}")
            return False

        # ШАГ 3: Найти и кликнуть по зданию
        if not self._find_and_click_building(emulator, building_name):
            logger.error(f"[{emulator_name}] ❌ Не удалось найти здание {building_name}")
            press_key(emulator, "BACK")  # Закрываем меню
            time.sleep(1)
            return False

        # ШАГ 4: Кликнуть "Подтвердить"
        if not self._click_confirm(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось кликнуть Подтвердить")
            press_key(emulator, "BACK")
            time.sleep(1)
            return False

        # ШАГ 5: Проверить что здание построено
        if not self._verify_construction(emulator, building_name):
            logger.error(f"[{emulator_name}] ❌ Здание не появилось после постройки")
            return False

        return True

    def _open_construction_menu(self, emulator: Dict) -> bool:
        """Открыть меню постройки (клик лопаты)"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Клик по иконке лопаты ({self.SHOVEL_ICON[0]}, {self.SHOVEL_ICON[1]})")
        tap(emulator, x=self.SHOVEL_ICON[0], y=self.SHOVEL_ICON[1])
        time.sleep(2)  # Ждем открытия меню

        return True

    def _select_category(self, emulator: Dict, category_name: str) -> bool:
        """
        Выбрать категорию здания

        Приоритет: шаблон → fallback координаты
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Выбор категории: {category_name}")

        # ПОПЫТКА 1: Поиск через шаблон
        template_path = self.CATEGORY_TEMPLATES.get(category_name)
        if template_path and os.path.exists(template_path):
            screenshot = get_screenshot(emulator)
            result = find_image(screenshot, template_path, threshold=self.THRESHOLD_CATEGORY)

            if result:
                center_x, center_y = result['center']
                logger.debug(f"[{emulator_name}] Найдена категория через шаблон: ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)
                return True

            logger.debug(f"[{emulator_name}] Категория не найдена через шаблон")

        # ПОПЫТКА 2: Fallback на координаты
        coords = self.CATEGORY_COORDS.get(category_name)
        if coords:
            logger.debug(f"[{emulator_name}] Используем fallback координаты: {coords}")
            tap(emulator, x=coords[0], y=coords[1])
            time.sleep(1.5)
            return True

        logger.error(f"[{emulator_name}] ❌ Категория {category_name} не найдена")
        return False

    def _find_and_click_building(self, emulator: Dict, building_name: str) -> bool:
        """
        Найти здание через свайпы + шаблоны

        На странице помещается 3 здания
        Максимум 4 свайпа = 5 страниц
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Поиск здания: {building_name}")

        template_path = self.BUILDING_TEMPLATES.get(building_name)
        if not template_path or not os.path.exists(template_path):
            logger.error(f"[{emulator_name}] ❌ Шаблон здания не найден: {template_path}")
            return False

        # Проверяем текущую страницу + MAX_SWIPES свайпов
        for swipe_attempt in range(self.MAX_SWIPES + 1):

            if swipe_attempt > 0:
                logger.debug(f"[{emulator_name}] Свайп {swipe_attempt}/{self.MAX_SWIPES}")
                swipe(emulator,
                      start_x=self.SWIPE_START[0], start_y=self.SWIPE_START[1],
                      end_x=self.SWIPE_END[0], end_y=self.SWIPE_END[1],
                      duration=300)
                time.sleep(1)

            # Ищем здание на текущей странице
            screenshot = get_screenshot(emulator)
            result = find_image(screenshot, template_path, threshold=self.THRESHOLD_BUILDING)

            if result:
                center_x, center_y = result['center']
                logger.debug(f"[{emulator_name}] ✅ Здание найдено: ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)
                return True

        logger.error(f"[{emulator_name}] ❌ Здание не найдено после {self.MAX_SWIPES} свайпов")
        return False

    def _click_confirm(self, emulator: Dict) -> bool:
        """
        Кликнуть кнопку "Подтвердить"

        Приоритет: шаблон → fallback координаты
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Клик по кнопке Подтвердить")

        # ПОПЫТКА 1: Поиск через шаблон
        if os.path.exists(self.CONFIRM_BUTTON_TEMPLATE):
            screenshot = get_screenshot(emulator)
            result = find_image(screenshot, self.CONFIRM_BUTTON_TEMPLATE,
                              threshold=self.THRESHOLD_BUTTON)

            if result:
                center_x, center_y = result['center']
                logger.debug(f"[{emulator_name}] Найдена кнопка через шаблон: ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(2)
                return True

            logger.debug(f"[{emulator_name}] Кнопка не найдена через шаблон")

        # ПОПЫТКА 2: Fallback на координаты
        logger.debug(f"[{emulator_name}] Используем fallback координаты: {self.CONFIRM_BUTTON}")
        tap(emulator, x=self.CONFIRM_BUTTON[0], y=self.CONFIRM_BUTTON[1])
        time.sleep(2)
        return True

    def _verify_construction(self, emulator: Dict, building_name: str) -> bool:
        """
        Проверить что здание построено

        Алгоритм:
        1. Проверить что кнопка "Подтвердить" исчезла
        2. Проверить через панель навигации что здание появилось
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Проверка постройки...")

        # ПРОВЕРКА 1: Кнопка "Подтвердить" исчезла
        time.sleep(2)
        screenshot = get_screenshot(emulator)

        if os.path.exists(self.CONFIRM_BUTTON_TEMPLATE):
            result = find_image(screenshot, self.CONFIRM_BUTTON_TEMPLATE,
                              threshold=self.THRESHOLD_BUTTON)

            if result:
                logger.warning(f"[{emulator_name}] ⚠️ Кнопка Подтвердить все еще видна")
                return False

            logger.debug(f"[{emulator_name}] ✅ Кнопка Подтвердить исчезла")

        # ПРОВЕРКА 2: Здание появилось в панели навигации
        # Импортируем панель навигации
        try:
            from functions.building.navigation_panel import NavigationPanel
            panel = NavigationPanel()

            # Открываем панель
            if not panel.open_navigation_panel(emulator):
                logger.warning(f"[{emulator_name}] ⚠️ Не удалось открыть панель навигации")
                return False

            # Парсим список зданий
            buildings = panel.parse_buildings_list(emulator)
            press_key(emulator, "BACK")  # Закрываем панель
            time.sleep(1)

            # Ищем здание в списке
            for building in buildings:
                if building['name'] == building_name and building['level'] >= 1:
                    logger.success(f"[{emulator_name}] ✅ Здание найдено в панели навигации: {building_name} Lv.{building['level']}")
                    return True

            logger.error(f"[{emulator_name}] ❌ Здание {building_name} не найдено в панели навигации")
            return False

        except Exception as e:
            logger.error(f"[{emulator_name}] ❌ Ошибка при проверке через панель навигации: {e}")
            return False