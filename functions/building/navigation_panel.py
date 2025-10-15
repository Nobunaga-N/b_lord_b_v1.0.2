"""
Панель навигации для строительства
Управление панелью быстрого доступа к зданиям
"""

import os
import time
from typing import List, Dict, Any, Optional
from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger


# Определяем базовую директорию проекта (корень проекта)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class NavigationPanel:
    """
    Класс для работы с панелью навигации (список зданий)

    Координаты панели: иконка (29, 481)
    Вкладки:
        - "Список дел" (95, 252)
        - "Список зданий" (291, 250)

    Разделы (7 штук):
        1. Вожак
        2. Мегазверь
        3. Битва (требует свайпа)
        4. Развитие (требует свайпа)
        5. Альянс
        6. Ресурсы (требует свайпа)
           - Подвкладки: Фрукты, Трава, Листья, Грунт, Песок, Вода, Мед
        7. Другие
    """

    # Координаты
    PANEL_ICON_COORDS = (29, 481)
    TAB_TASKS_COORDS = (95, 252)
    TAB_BUILDINGS_COORDS = (291, 250)
    BUTTON_GO_X = 330  # X координата кнопки "Перейти"

    # Шаблоны изображений (используем абсолютные пути)
    TEMPLATES = {
        'panel_icon': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'navigation_icon.png'),
        'arrow_down': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'arrow_down.png'),
        'arrow_right': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'arrow_right.png'),
        'arrow_down_sub': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'arrow_down_sub.png'),
        'arrow_right_sub': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'arrow_right_sub.png'),
    }

    # Разделы панели навигации
    SECTIONS = {
        'Вожак': {'requires_scroll': False},
        'Мегазверь': {'requires_scroll': False},
        'Битва': {'requires_scroll': True},
        'Развитие': {'requires_scroll': True},
        'Альянс': {'requires_scroll': False},
        'Ресурсы': {'requires_scroll': True, 'has_subsections': True},
        'Другие': {'requires_scroll': False},
    }

    def __init__(self):
        """Инициализация панели навигации"""
        self.ocr = OCREngine()

        # Проверяем что все шаблоны существуют
        logger.debug(f"BASE_DIR: {BASE_DIR}")
        for name, path in self.TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "❌"
            logger.debug(f"{status} Шаблон '{name}': {path}")

        logger.info("✅ NavigationPanel инициализирована")

    def open_navigation_panel(self, emulator: Dict) -> bool:
        """
        Открыть панель навигации

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если панель открылась
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Проверить что панель не открыта
        if self.is_navigation_open(emulator):
            logger.debug(f"[{emulator_name}] Панель навигации уже открыта")
            return True

        # Клик по иконке панели
        logger.info(f"[{emulator_name}] Открытие панели навигации...")
        tap(emulator, x=self.PANEL_ICON_COORDS[0], y=self.PANEL_ICON_COORDS[1])
        time.sleep(1.5)

        # Проверить что панель открылась
        if self.is_navigation_open(emulator):
            logger.success(f"[{emulator_name}] ✅ Панель навигации открыта")
            return True
        else:
            logger.error(f"[{emulator_name}] ❌ Не удалось открыть панель навигации")
            return False

    def close_navigation_panel(self, emulator: Dict) -> bool:
        """
        Закрыть панель навигации

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если панель закрылась
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Закрытие панели навигации...")
        press_key(emulator, "ESC")
        time.sleep(0.5)

        # Проверить что панель закрылась
        if not self.is_navigation_open(emulator):
            logger.debug(f"[{emulator_name}] ✅ Панель навигации закрыта")
            return True
        else:
            logger.warning(f"[{emulator_name}] ⚠️ Панель навигации не закрылась")
            return False

    def is_navigation_open(self, emulator: Dict) -> bool:
        """
        Проверить открыта ли панель навигации

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если панель открыта
        """
        # Ищем любую характерную вкладку панели
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        # Можно проверить через OCR наличие текста "Список зданий" или "Список дел"
        # Или через поиск характерных элементов интерфейса
        # Для упрощения используем простую проверку через OCR
        elements = self.ocr.recognize_text(screenshot, min_confidence=0.5)

        for elem in elements:
            text = elem['text'].lower()
            if 'список' in text and ('зданий' in text or 'дел' in text):
                return True

        return False

    def switch_to_buildings_tab(self, emulator: Dict) -> bool:
        """
        Переключиться на вкладку "Список зданий"

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если переключились
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Переключение на 'Список зданий'...")
        tap(emulator, x=self.TAB_BUILDINGS_COORDS[0], y=self.TAB_BUILDINGS_COORDS[1])
        time.sleep(0.5)

        return True

    def collapse_all_sections(self, emulator: Dict) -> bool:
        """
        Свернуть все разделы панели навигации

        КРИТИЧНЫЙ АЛГОРИТМ:
        1. СНАЧАЛА сворачиваем подвкладки (arrow_down_sub)
        2. ПОТОМ сворачиваем основные разделы (arrow_down)
        3. Проверяем Y координату (должна быть > 200 чтобы не кликнуть на вкладки вверху)
        4. Цикл пока не останется только стрелки "вправо"

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если все разделы свёрнуты
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emulator_name}] Сворачивание всех разделов панели...")

        max_attempts = 20
        attempt = 0

        # СНИЖАЕМ THRESHOLD для более надёжного поиска
        THRESHOLD_MAIN = 0.65
        THRESHOLD_SUB = 0.65

        # Минимальная Y координата для стрелок разделов (чтобы не кликать на вкладки вверху)
        MIN_Y_COORDINATE = 200

        while attempt < max_attempts:
            attempt += 1

            # Получить скриншот
            screenshot = get_screenshot(emulator)
            if screenshot is None:
                logger.error(f"[{emulator_name}] ❌ Не удалось получить скриншот")
                return False

            # ШАГ 1: СНАЧАЛА ищем подразделы (arrow_down_sub)
            arrow_down_sub = find_image(emulator, self.TEMPLATES['arrow_down_sub'],
                                       threshold=THRESHOLD_SUB,
                                       debug_name=f"collapse_sub_attempt_{attempt}")

            if arrow_down_sub is not None:
                # Проверяем Y координату
                if arrow_down_sub[1] >= MIN_Y_COORDINATE:
                    logger.debug(f"[{emulator_name}] Найден развёрнутый подраздел на Y={arrow_down_sub[1]}, сворачиваю...")
                    tap(emulator, x=arrow_down_sub[0], y=arrow_down_sub[1])
                    time.sleep(0.6)
                    continue
                else:
                    logger.warning(f"[{emulator_name}] ⚠️ Подраздел найден на Y={arrow_down_sub[1]} < {MIN_Y_COORDINATE}, пропускаю")

            # ШАГ 2: ПОТОМ ищем основные разделы (arrow_down)
            arrow_down = find_image(emulator, self.TEMPLATES['arrow_down'],
                                   threshold=THRESHOLD_MAIN,
                                   debug_name=f"collapse_main_attempt_{attempt}")

            if arrow_down is not None:
                # Проверяем Y координату
                if arrow_down[1] >= MIN_Y_COORDINATE:
                    logger.debug(f"[{emulator_name}] Сворачивание раздела на Y={arrow_down[1]} (попытка {attempt})...")
                    tap(emulator, x=arrow_down[0], y=arrow_down[1])
                    time.sleep(0.6)
                    continue
                else:
                    logger.warning(f"[{emulator_name}] ⚠️ Раздел найден на Y={arrow_down[1]} < {MIN_Y_COORDINATE}, пропускаю")

            # ШАГ 3: Если ничего не найдено - всё свёрнуто!
            if arrow_down_sub is None and arrow_down is None:
                logger.success(f"[{emulator_name}] ✅ Все разделы свёрнуты (попыток: {attempt})")
                break

        if attempt >= max_attempts:
            logger.warning(f"[{emulator_name}] ⚠️ Достигнут лимит попыток сворачивания ({max_attempts})")
            return False

        logger.success(f"[{emulator_name}] ✅ Все разделы свёрнуты корректно")
        return True

    def open_section(self, emulator: Dict, section_name: str) -> bool:
        """
        Открыть раздел по имени

        Args:
            emulator: объект эмулятора
            section_name: название раздела ("Развитие", "Ресурсы" и т.д.)

        Returns:
            bool: True если раздел открылся
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if section_name not in self.SECTIONS:
            logger.error(f"[{emulator_name}] ❌ Неизвестный раздел: {section_name}")
            return False

        logger.debug(f"[{emulator_name}] Открытие раздела: {section_name}")

        # Получить скриншот
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        # Найти раздел через OCR
        elements = self.ocr.recognize_text(screenshot, min_confidence=0.5)

        for elem in elements:
            if section_name.lower() in elem['text'].lower():
                # Нашли раздел, кликаем по нему
                tap(emulator, x=elem['x'], y=elem['y'])
                time.sleep(0.5)

                logger.success(f"[{emulator_name}] ✅ Раздел '{section_name}' открыт")
                return True

        logger.warning(f"[{emulator_name}] ⚠️ Раздел '{section_name}' не найден на экране")
        return False

    def scroll_in_panel(self, emulator: Dict, direction: str = 'down') -> bool:
        """
        Свайп внутри панели навигации

        Args:
            emulator: объект эмулятора
            direction: направление ('down', 'up')

        Returns:
            bool: True если свайп выполнен
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if direction == 'down':
            # Вниз (для прокрутки списка зданий)
            swipe(emulator, x1=270, y1=700, x2=270, y2=300, duration=300)
            logger.debug(f"[{emulator_name}] Свайп вниз в панели")
        elif direction == 'up':
            # Вверх (для возврата к началу списка)
            swipe(emulator, x1=270, y1=300, x2=270, y2=700, duration=300)
            logger.debug(f"[{emulator_name}] Свайп вверх в панели")
        else:
            logger.error(f"[{emulator_name}] ❌ Неизвестное направление: {direction}")
            return False

        time.sleep(0.5)
        return True

    def get_buildings_in_section(self, emulator: Dict, section_name: str) -> List[Dict[str, Any]]:
        """
        Получить список зданий в разделе

        Args:
            emulator: объект эмулятора
            section_name: название раздела ("Развитие", "Ресурсы" и т.д.)

        Returns:
            list: [{"name": "...", "level": X, "y": Y}, ...]
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        emulator_id = emulator.get('id', '?')

        logger.info(f"[{emulator_name}] Парсинг зданий в разделе: {section_name}")

        # 1. Открыть панель навигации
        if not self.open_navigation_panel(emulator):
            return []

        # 2. Переключиться на "Список зданий"
        self.switch_to_buildings_tab(emulator)

        # 3. Свернуть все разделы
        if not self.collapse_all_sections(emulator):
            logger.warning(f"[{emulator_name}] ⚠️ Не удалось свернуть все разделы")

        # 4. Открыть нужный раздел
        if not self.open_section(emulator, section_name):
            return []

        # 5. Получить скриншот
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return []

        # 6. Парсинг через OCR
        buildings = self.ocr.parse_navigation_panel(screenshot, emulator_id=emulator_id)

        logger.success(f"[{emulator_name}] ✅ Найдено зданий: {len(buildings)}")

        return buildings

    def find_building_in_all_sections(self, emulator: Dict, building_name: str) -> Optional[Dict[str, Any]]:
        """
        Найти здание во всех разделах

        Args:
            emulator: объект эмулятора
            building_name: название здания (с римскими цифрами если есть)

        Returns:
            dict: {"name": "...", "level": X, "y": Y, "section": "..."} или None
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emulator_name}] Поиск здания: {building_name}")

        # Проходим по всем разделам
        for section_name in self.SECTIONS.keys():
            buildings = self.get_buildings_in_section(emulator, section_name)

            for building in buildings:
                if building['name'] == building_name:
                    building['section'] = section_name
                    logger.success(f"[{emulator_name}] ✅ Здание найдено в разделе: {section_name}")
                    return building

        logger.error(f"[{emulator_name}] ❌ Здание не найдено: {building_name}")
        return None

    def go_to_building(self, emulator: Dict, building_name: str) -> bool:
        """
        Перейти к зданию через панель навигации

        Args:
            emulator: объект эмулятора
            building_name: название здания (с римскими цифрами если есть)

        Returns:
            bool: True если успешно перешли
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emulator_name}] Переход к зданию: {building_name}")

        # 1. Найти здание во всех разделах
        target = self.find_building_in_all_sections(emulator, building_name)

        if not target:
            logger.error(f"[{emulator_name}] ❌ Здание не найдено: {building_name}")
            return False

        # 2. Клик по кнопке "Перейти" (X=330, Y=координата здания)
        tap(emulator, x=self.BUTTON_GO_X, y=target['y'])
        time.sleep(2)  # Ожидание загрузки

        logger.success(f"[{emulator_name}] ✅ Перешли к зданию: {building_name}")

        # 3. Закрыть панель навигации
        self.close_navigation_panel(emulator)

        return True