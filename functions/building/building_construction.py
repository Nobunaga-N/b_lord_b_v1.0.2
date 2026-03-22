"""
Модуль постройки новых зданий
Обрабатывает процесс постройки через меню лопаты

Версия: 2.0 (УПРОЩЕННАЯ)
Дата обновления: 2025-01-24
Изменения:
- УБРАНА обработка окон ресурсов (окно закрывается автоматически после "Построить")
- УБРАН парсинг таймера (не нужен для постройки)
- УПРОЩЕНА логика до 7 шагов
- Возвращается просто bool вместо (bool, timer)
"""

import os
import time
from typing import Dict, Optional, Tuple
from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image
from utils.logger import logger


# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BuildingConstruction:
    """Класс для постройки новых зданий"""

    # Координаты
    SHOVEL_ICON = (497, 768)  # Иконка лопаты
    CONFIRM_BUTTON = (327, 552)  # Кнопка "Подтвердить"
    HAMMER_ICON = (268, 517)  # Молоточек на месте здания
    BUILD_BUTTON = (327, 552)  # Кнопка "Построить"

    # Свайпы для поиска зданий в меню лопаты
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
        "Склад Фруктов III": "Фрукты",
        "Склад Листьев III": "Листья",
        "Склад Грунта III": "Грунт",
        "Склад Песка III": "Песок",
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
        "Склад Песка III": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'sklad_peska_3.png'),
        "Склад Листьев III": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'sklad_listev_3.png'),
        "Склад Грунта III": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'sklad_grunta_3.png'),
        "Склад Фруктов III": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'buildings', 'sklad_fruktov_3.png'),
    }

    # Шаблоны кнопок и иконок
    CONFIRM_BUTTON_TEMPLATE = os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'button_confirm.png')
    HAMMER_ICON_TEMPLATE = os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'hammer_icon.png')
    BUILD_BUTTON_TEMPLATE = os.path.join(BASE_DIR, 'data', 'templates', 'building', 'construction', 'button_build.png')

    # Пороги распознавания
    THRESHOLD_CATEGORY = 0.8
    THRESHOLD_BUILDING = 0.85
    THRESHOLD_BUTTON = 0.85
    THRESHOLD_HAMMER = 0.8
    THRESHOLD_BUILD = 0.85

    def __init__(self):
        """Инициализация модуля постройки"""
        logger.info("🏗️ Инициализация BuildingConstruction...")

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

    def construct_building(self, emulator: Dict, building_name: str,
                           building_index: Optional[int] = None) -> Tuple[bool, Optional[int]]:
        """
        ГЛАВНЫЙ МЕТОД - Построить новое здание

        Args:
            emulator: объект эмулятора
            building_name: название здания
            building_index: индекс (для множественных зданий)

        Returns:
             Tuple[bool, Optional[int]]: (успех, уровень_здания)
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        building_display = f"{building_name}" + (f" #{building_index}" if building_index else "")

        logger.info(f"[{emulator_name}] 🏗️ Начало постройки: {building_display}")

        # Попытка 1
        success, level = self._try_construct(emulator, building_name, building_index)
        if success:
            logger.success(f"[{emulator_name}] ✅ Здание построено: {building_display}")
            return True, level

        logger.warning(f"[{emulator_name}] ⚠️ Первая попытка неудачна, повторяем...")
        time.sleep(2)

        # Попытка 2
        success, level = self._try_construct(emulator, building_name, building_index)
        if success:
            logger.success(f"[{emulator_name}] ✅ Здание построено (попытка 2): {building_display}")
            return True, level

        logger.error(f"[{emulator_name}] ❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось построить {building_display}")
        return False, None

    def _ensure_shovel_visible(self, emulator: Dict, max_attempts: int = 4) -> bool:
        """
        Умная проверка видимости иконки лопаты

        Проблема: Если открыта панель навигации или другое меню,
        клик ESC вызывает окно "Выйти из игры?", после чего клик по лопате
        закрывает это окно вместо открытия меню постройки.

        Решение: Проверяем наличие лопаты ПЕРЕД каждым ESC.
        Если лопата видна (95% совпадение) - не нажимаем ESC.

        Алгоритм:
        1. Проверить есть ли лопата (threshold=0.95)
        2. Если ДА → готово, возвращаем True
        3. Если НЕТ → нажать ESC, подождать 0.5с
        4. Повторить до max_attempts раз
        5. Если после всех попыток лопаты нет → False

        Args:
            emulator: объект эмулятора
            max_attempts: максимум попыток ESC (по умолчанию 4)

        Returns:
            bool: True если лопата видна, False если не удалось найти
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Путь к шаблону лопаты
        shovel_template = os.path.join(BASE_DIR, 'data', 'templates', 'building', 'shovel_icon.png')

        # Проверяем существование шаблона
        if not os.path.exists(shovel_template):
            logger.warning(f"[{emulator_name}] ⚠️ Шаблон лопаты не найден: {shovel_template}")
            logger.warning(f"[{emulator_name}] ⚠️ Пропускаем проверку, надеемся что лопата видна")
            return True

        logger.debug(f"[{emulator_name}] 🔍 Проверка видимости иконки лопаты...")

        for attempt in range(1, max_attempts + 1):
            # Проверяем наличие лопаты с высоким порогом
            result = find_image(emulator, shovel_template, threshold=0.95)

            if result is not None:
                logger.success(f"[{emulator_name}] ✅ Лопата видна (попытка {attempt}/{max_attempts})")
                return True

            logger.debug(f"[{emulator_name}] ❌ Лопата не видна (попытка {attempt}/{max_attempts})")

            # Если не последняя попытка - нажимаем ESC
            if attempt < max_attempts:
                logger.debug(f"[{emulator_name}] 🔄 Нажимаем ESC для закрытия открытых окон...")
                press_key(emulator, "ESC")
                time.sleep(0.5)

        # После всех попыток лопата не найдена
        logger.error(f"[{emulator_name}] ❌ КРИТИЧЕСКАЯ ОШИБКА: Лопата не видна после {max_attempts} попыток ESC!")
        return False

    def _try_construct(self, emulator: Dict, building_name: str,
                           building_index: Optional[int] = None) -> Tuple[bool, Optional[int]]:
        """
        Одна попытка постройки здания

        Алгоритм:
        1. Клик лопаты
        2. Выбор категории
        3. Поиск и клик здания
        4. Клик "Подтвердить"
        5. Клик молоточка
        6. Клик "Построить" (окно закрывается автоматически)
        7. Проверка через панель навигации

        Returns:
            Tuple[bool, Optional[int]]: (успех, уровень_здания или None)
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ШАГ 0: УМНАЯ ПРОВЕРКА ВИДИМОСТИ ЛОПАТЫ (НОВОЕ!)
        logger.debug(f"[{emulator_name}] ШАГ 0: Проверка видимости иконки лопаты")
        if not self._ensure_shovel_visible(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось добиться видимости лопаты")
            return False, None

        # ШАГ 1: Открываем меню постройки
        logger.debug(f"[{emulator_name}] ШАГ 1: Открываем меню постройки (клик лопаты)")
        if not self._open_construction_menu(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось открыть меню постройки")
            return False, None

        # ШАГ 2: Выбор категории
        logger.debug(f"[{emulator_name}] ШАГ 2: Выбираем категорию")
        category = self._get_building_category(building_name)
        if not category:
            logger.error(f"[{emulator_name}] ❌ Категория не найдена для {building_name}")
            return False, None

        if not self._select_category(emulator, category):
            logger.error(f"[{emulator_name}] ❌ Не удалось выбрать категорию: {category}")
            return False, None

        # ШАГ 3: Поиск здания через свайпы + клик
        logger.debug(f"[{emulator_name}] ШАГ 3: Ищем и кликаем здание: {building_name}")
        if not self._find_and_click_building(emulator, building_name):
            logger.error(f"[{emulator_name}] ❌ Не удалось найти здание: {building_name}")
            return False, None

        # ШАГ 4: Клик "Подтвердить" (выбор места для здания)
        logger.debug(f"[{emulator_name}] ШАГ 4: Кликаем 'Подтвердить'")
        if not self._click_confirm(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось кликнуть 'Подтвердить'")
            return False, None

        # ШАГ 5-6: Клик молоточка → клик "Построить" (окно закроется автоматически)
        logger.debug(f"[{emulator_name}] ШАГ 5-6: Кликаем молоточек и 'Построить'")
        if not self._click_hammer_and_build(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось кликнуть молоточек/построить")
            return False, None

        # ШАГ 7: ПРОВЕРКА ЧЕРЕЗ ПАНЕЛЬ НАВИГАЦИИ
        logger.debug(f"[{emulator_name}] ШАГ 7: Проверяем постройку через панель навигации")
        verification_result, actual_level = self._verify_construction_in_panel(
            emulator, building_name, building_index
        )

        if verification_result == "level_found":
            # ✅ Здание построено или уже было построено
            logger.success(f"[{emulator_name}] ✅ Здание подтверждено, уровень: {actual_level}")

            # Возвращаем статус И уровень для обновления БД
            return True, actual_level

        elif verification_result == "level_0":
            # ⚠️ Уровень 0, нужно достроить
            logger.warning(f"[{emulator_name}] ⚠️ Уровень 0, достраиваем...")
            if not self._finish_incomplete_construction(emulator, building_name, building_index):
                logger.error(f"[{emulator_name}] ❌ Не удалось достроить здание")
                return False, None
            logger.success(f"[{emulator_name}] ✅ Здание достроено успешно")
            return True, 1  # После достройки = уровень 1

        elif verification_result == "not_found":
            # ❌ Здания нет
            logger.error(f"[{emulator_name}] ❌ Здание не найдено в панели навигации")
            return False, None

        else:
            logger.error(f"[{emulator_name}] ❌ Неизвестный результат: {verification_result}")
            return False, None

    def _verify_construction_in_panel(self, emulator: Dict, building_name: str,
                                      building_index: Optional[int] = None) -> Tuple[str, Optional[int]]:
        """
        Проверить постройку через панель навигации

        ИСПРАВЛЕНО: Возвращает (статус, уровень) вместо только статуса

        Args:
            emulator: объект эмулятора
            building_name: название здания
            building_index: индекс для множественных зданий

        Returns:
            Tuple[str, Optional[int]]: (статус, уровень)
                - ("level_found", N) - здание найдено с уровнем N >= 1
                - ("level_0", 0) - здание есть но уровень 0 (не достроено)
                - ("not_found", None) - здание не найдено вообще
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        building_display = f"{building_name}" + (f" #{building_index}" if building_index else "")

        logger.debug(f"[{emulator_name}] 🔍 Проверяем постройку в панели навигации: {building_display}")

        # Импортируем NavigationPanel
        from functions.building.navigation_panel import NavigationPanel
        nav_panel = NavigationPanel()

        # Закрываем все открытые окна
        press_key(emulator, "ESC")
        time.sleep(0.5)
        press_key(emulator, "ESC")
        time.sleep(0.5)

        # Проверяем здания
        if building_index:
            # Для множественных зданий - проверяем до 10 экземпляров
            logger.debug(f"[{emulator_name}] 🔍 Ищем построенное здание (любой уровень >= 1)")

            all_levels = []
            for idx in range(1, 11):
                try:
                    level = nav_panel.get_building_level(emulator, building_name, idx)
                    if level is not None:
                        all_levels.append((idx, level))
                        logger.debug(f"[{emulator_name}] Найдено: {building_name} #{idx} → Lv.{level}")

                        # Если нашли уровень >= 1 - прерываем
                        if level >= 1:
                            logger.success(f"[{emulator_name}] ✅ Найдено здание Lv.{level}, прерываем поиск")
                            break
                except Exception as e:
                    logger.debug(f"[{emulator_name}] Пропускаем #{idx}: {e}")
                    continue

            if not all_levels:
                logger.error(f"[{emulator_name}] ❌ Здания не найдены вообще")
                return ("not_found", None)

            # Проверяем уровни
            found_built = [(idx, level) for idx, level in all_levels if level >= 1]
            found_level_0 = [(idx, level) for idx, level in all_levels if level == 0]

            logger.debug(f"[{emulator_name}] Найденные уровни: {all_levels}")

            if found_built:
                # Берем первое найденное здание с уровнем >= 1
                idx, level = found_built[0]
                logger.success(f"[{emulator_name}] ✅ Постройка подтверждена! #{idx} Lv.{level}")
                return ("level_found", level)
            elif found_level_0:
                logger.warning(f"[{emulator_name}] ⚠️ Найдено здание Lv.0 (не достроено)")
                return ("level_0", 0)
            else:
                return ("not_found", None)
        else:
            # Для уникального здания
            level = nav_panel.get_building_level(emulator, building_name, None)

            if level is None:
                logger.error(f"[{emulator_name}] ❌ Здание не найдено в панели навигации")
                return ("not_found", None)

            logger.debug(f"[{emulator_name}] Найдено: {building_display} Lv.{level}")

            if level >= 1:
                logger.success(f"[{emulator_name}] ✅ Здание подтверждено с уровнем {level}")
                return ("level_found", level)
            elif level == 0:
                logger.warning(f"[{emulator_name}] ⚠️ Здание найдено с уровнем 0")
                return ("level_0", 0)
            else:
                return ("not_found", None)

    def _finish_incomplete_construction(self, emulator: Dict, building_name: str,
                                        building_index: Optional[int] = None) -> bool:
        """
        Достроить здание если уровень = 0

        Алгоритм:
        1. Кликаем "Перейти" в панели навигации (уже открыта)
        2. Попадаем к зданию с молоточком
        3. Кликаем молоточек → "Построить"
        4. Проверяем уровень снова (должен стать 1)

        Args:
            emulator: объект эмулятора
            building_name: название здания
            building_index: индекс для множественных зданий

        Returns:
            bool: True если успешно достроили
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        building_display = f"{building_name}" + (f" #{building_index}" if building_index else "")

        logger.info(f"[{emulator_name}] 🔨 Достраиваем незавершенное здание: {building_display}")

        # Импортируем NavigationPanel
        from functions.building.navigation_panel import NavigationPanel
        nav_panel = NavigationPanel()

        # Кликаем "Перейти" (панель навигации уже открыта из _verify_construction_in_panel)
        if not nav_panel.navigate_to_building(emulator, building_name, building_index):
            logger.error(f"[{emulator_name}] ❌ Не удалось перейти к зданию")
            return False

        time.sleep(1.5)

        # Кликаем молоточек + "Построить"
        if not self._click_hammer_and_build(emulator):
            logger.error(f"[{emulator_name}] ❌ Не удалось кликнуть молоточек/построить")
            return False

        # Проверяем уровень снова
        time.sleep(2)
        verification_result, actual_level = self._verify_construction_in_panel(
            emulator, building_name, building_index
        )
        if verification_result == "level_found" and actual_level and actual_level >= 1:
            logger.success(f"[{emulator_name}] ✅ Здание достроено, уровень: {actual_level}")
            return True
        else:
            logger.error(f"[{emulator_name}] ❌ После достройки статус: {verification_result}, уровень: {actual_level}")
            return False

    # ========================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================

    def _open_construction_menu(self, emulator: Dict) -> bool:
        """Открыть меню постройки (клик лопаты)"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Клик по лопате ({self.SHOVEL_ICON[0]}, {self.SHOVEL_ICON[1]})")
        tap(emulator, x=self.SHOVEL_ICON[0], y=self.SHOVEL_ICON[1])
        time.sleep(2)

        return True

    def _get_building_category(self, building_name: str) -> Optional[str]:
        """
        Получить категорию здания

        Args:
            building_name: название здания

        Returns:
            категория или None
        """
        category = self.BUILDING_TO_CATEGORY.get(building_name)
        if not category:
            logger.error(f"❌ Категория не найдена для здания: {building_name}")
            return None

        logger.debug(f"Категория для '{building_name}': {category}")
        return category

    def _select_category(self, emulator: Dict, category_name: str) -> bool:
        """
        Выбрать категорию здания

        Args:
            emulator: объект эмулятора
            category_name: название категории

        Returns:
            bool: True если успешно
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Выбор категории: {category_name}")

        # Сначала пытаемся найти через шаблон
        template_path = self.CATEGORY_TEMPLATES.get(category_name)
        if template_path and os.path.exists(template_path):
            result = find_image(emulator, template_path, threshold=self.THRESHOLD_CATEGORY)
            if result:
                center_x, center_y = result
                logger.debug(f"[{emulator_name}] Категория найдена через шаблон: ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)
                return True

        # Fallback на координаты
        coords = self.CATEGORY_COORDS.get(category_name)
        if coords:
            logger.debug(f"[{emulator_name}] Используем fallback координаты: {coords}")
            tap(emulator, x=coords[0], y=coords[1])
            time.sleep(1.5)
            return True

        logger.error(f"[{emulator_name}] ❌ Категория не найдена: {category_name}")
        return False

    def _find_and_click_building(self, emulator: Dict, building_name: str) -> bool:
        """
        Найти здание через свайпы + шаблоны и кликнуть

        Args:
            emulator: объект эмулятора
            building_name: название здания

        Returns:
            bool: True если успешно
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        template_path = self.BUILDING_TEMPLATES.get(building_name)
        if not template_path or not os.path.exists(template_path):
            logger.error(f"[{emulator_name}] ❌ Шаблон не найден для здания: {building_name}")
            return False

        logger.debug(f"[{emulator_name}] Поиск здания: {building_name}")

        # Попытка найти без свайпов
        for swipe_attempt in range(self.MAX_SWIPES + 1):
            if swipe_attempt > 0:
                logger.debug(f"[{emulator_name}] Свайп {swipe_attempt}/{self.MAX_SWIPES}")
                swipe(emulator,
                      self.SWIPE_START_X, self.SWIPE_START_Y,
                      self.SWIPE_END_X, self.SWIPE_END_Y,
                      600)
                time.sleep(2)

            result = find_image(emulator, template_path, threshold=self.THRESHOLD_BUILDING)
            if result:
                center_x, center_y = result
                logger.debug(f"[{emulator_name}] Здание найдено: ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)
                return True

        logger.error(f"[{emulator_name}] ❌ Здание не найдено после {self.MAX_SWIPES} свайпов")
        return False

    def _click_confirm(self, emulator: Dict) -> bool:
        """
        Кликнуть кнопку 'Подтвердить' (выбор места для здания)

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если успешно
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Поиск кнопки 'Подтвердить'...")

        # Пытаемся найти через шаблон
        if os.path.exists(self.CONFIRM_BUTTON_TEMPLATE):
            result = find_image(emulator, self.CONFIRM_BUTTON_TEMPLATE, threshold=self.THRESHOLD_BUTTON)
            if result:
                center_x, center_y = result
                logger.debug(f"[{emulator_name}] Кнопка 'Подтвердить' найдена через шаблон: ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(2)
                return True

        # Fallback на координаты
        logger.debug(f"[{emulator_name}] Используем fallback координаты для 'Подтвердить'")
        tap(emulator, x=self.CONFIRM_BUTTON[0], y=self.CONFIRM_BUTTON[1])
        time.sleep(2)
        return True

    def _click_hammer_and_build(self, emulator: Dict) -> bool:
        """
        Кликнуть молоточек и кнопку 'Построить'

        Процесс:
        1. После 'Подтвердить' появляется место под здание с молоточком
        2. Ищем и кликаем молоточек (через шаблон)
        3. Открывается меню постройки
        4. Ищем и кликаем 'Построить' (окно закроется автоматически)

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если успешно
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