"""
Панель навигации для строительства
Управление панелью быстрого доступа к зданиям
Версия с поддержкой YAML конфигурации
"""

import os
import time
import yaml
from typing import List, Dict, Any, Optional, Tuple
from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class NavigationPanel:
    """
    Класс для работы с панелью навигации (список зданий)

    Поддерживает:
    - Навигацию через конфигурацию YAML
    - Автоматические свайпы для доступа к разделам
    - Работу с подвкладками (например, Ресурсы)
    - Умное сворачивание/разворачивание разделов
    """

    # Координаты
    PANEL_ICON_COORDS = (29, 481)
    TAB_TASKS_COORDS = (95, 252)
    TAB_BUILDINGS_COORDS = (291, 250)
    BUTTON_GO_X = 330  # X координата кнопки "Перейти"
    BUILDING_CENTER = (268, 517)  # Центр здания после "Перейти"

    # Шаблоны изображений
    TEMPLATES = {
        'panel_icon': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'navigation_icon.png'),
        'arrow_down': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'arrow_down.png'),
        'arrow_right': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'arrow_right.png'),
        'arrow_down_sub': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'arrow_down_sub.png'),
        'arrow_right_sub': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'arrow_right_sub.png'),
    }

    def __init__(self):
        """Инициализация панели навигации"""
        self.ocr = OCREngine()
        self.config = self._load_config()

        # Проверяем что конфиг загружен
        if not self.config:
            logger.error("❌ Не удалось загрузить конфигурацию building_navigation.yaml")
        else:
            logger.info("✅ Конфигурация building_navigation.yaml загружена")

        # Проверяем шаблоны
        for name, path in self.TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "❌"
            logger.debug(f"{status} Шаблон '{name}': {path}")

        logger.info("✅ NavigationPanel инициализирована")

    def _load_config(self) -> Optional[Dict]:
        """
        Загрузить конфигурацию из building_navigation.yaml

        Returns:
            dict: конфигурация или None при ошибке
        """
        config_path = os.path.join(BASE_DIR, 'configs', 'building_navigation.yaml')

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            logger.debug(f"✅ Конфиг загружен из {config_path}")
            return config
        except FileNotFoundError:
            logger.error(f"❌ Файл не найден: {config_path}")
            return None
        except yaml.YAMLError as e:
            logger.error(f"❌ Ошибка парсинга YAML: {e}")
            return None

    def get_building_config(self, building_name: str) -> Optional[Dict]:
        """
        Получить конфигурацию здания из YAML

        Args:
            building_name: название здания

        Returns:
            dict: конфигурация здания или None
        """
        if not self.config:
            return None

        # Поиск в navigation.sections
        navigation = self.config.get('navigation', {})
        sections = navigation.get('sections', {})

        for section_name, section_data in sections.items():
            # Проверяем здания в секции
            buildings = section_data.get('buildings', [])
            for building in buildings:
                if building['name'] == building_name:
                    # Добавляем информацию о секции
                    building['section'] = section_name
                    building['section_data'] = section_data
                    return building

            # Проверяем подвкладки
            if section_data.get('has_subsections'):
                subsections = section_data.get('subsections', {})
                for subsection_name, subsection_data in subsections.items():
                    buildings = subsection_data.get('buildings', [])
                    for building in buildings:
                        if building['name'] == building_name:
                            building['section'] = section_name
                            building['subsection'] = subsection_name
                            building['section_data'] = section_data
                            building['subsection_data'] = subsection_data
                            return building

        # Поиск в tasks_tab
        tasks_tab = self.config.get('tasks_tab', {})
        buildings = tasks_tab.get('buildings', [])
        for building in buildings:
            if building['name'] == building_name:
                building['from_tasks_tab'] = True
                return building

        logger.warning(f"⚠️ Здание '{building_name}' не найдено в конфигурации")
        return None

    def get_all_testable_buildings(self) -> List[Dict]:
        """
        Получить список всех testable зданий из конфигурации

        Returns:
            list: [{"name": "...", "section": "...", ...}, ...]
        """
        testable = []

        if not self.config:
            return testable

        # Из navigation.sections
        navigation = self.config.get('navigation', {})
        sections = navigation.get('sections', {})

        for section_name, section_data in sections.items():
            # Здания в секции
            buildings = section_data.get('buildings', [])
            for building in buildings:
                if building.get('testable', False):
                    building['section'] = section_name
                    building['from_tasks_tab'] = False
                    testable.append(building.copy())

            # Подвкладки
            if section_data.get('has_subsections'):
                subsections = section_data.get('subsections', {})
                for subsection_name, subsection_data in subsections.items():
                    buildings = subsection_data.get('buildings', [])
                    for building in buildings:
                        if building.get('testable', False):
                            building['section'] = section_name
                            building['subsection'] = subsection_name
                            building['from_tasks_tab'] = False
                            testable.append(building.copy())

        # Из tasks_tab
        tasks_tab = self.config.get('tasks_tab', {})
        buildings = tasks_tab.get('buildings', [])
        for building in buildings:
            if building.get('testable', False):
                building['from_tasks_tab'] = True
                testable.append(building.copy())

        logger.info(f"📊 Найдено testable зданий: {len(testable)}")
        return testable

    def open_navigation_panel(self, emulator: Dict) -> bool:
        """Открыть панель навигации"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if self.is_navigation_open(emulator):
            logger.debug(f"[{emulator_name}] Панель навигации уже открыта")
            return True

        logger.info(f"[{emulator_name}] Открытие панели навигации...")
        tap(emulator, x=self.PANEL_ICON_COORDS[0], y=self.PANEL_ICON_COORDS[1])
        time.sleep(1.5)

        if self.is_navigation_open(emulator):
            logger.success(f"[{emulator_name}] ✅ Панель навигации открыта")
            return True
        else:
            logger.error(f"[{emulator_name}] ❌ Не удалось открыть панель навигации")
            return False

    def close_navigation_panel(self, emulator: Dict) -> bool:
        """Закрыть панель навигации"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Закрытие панели навигации...")
        press_key(emulator, "ESC")
        time.sleep(0.5)

        if not self.is_navigation_open(emulator):
            logger.debug(f"[{emulator_name}] ✅ Панель навигации закрыта")
            return True
        else:
            logger.warning(f"[{emulator_name}] ⚠️ Панель навигации не закрылась")
            return False

    def is_navigation_open(self, emulator: Dict) -> bool:
        """Проверить открыта ли панель навигации"""
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        elements = self.ocr.recognize_text(screenshot, min_confidence=0.5)

        for elem in elements:
            text = elem['text'].lower()
            if 'список' in text and ('зданий' in text or 'дел' in text):
                return True

        return False

    def switch_to_buildings_tab(self, emulator: Dict) -> bool:
        """Переключиться на вкладку 'Список зданий'"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Переключение на 'Список зданий'")
        tap(emulator, x=self.TAB_BUILDINGS_COORDS[0], y=self.TAB_BUILDINGS_COORDS[1])
        time.sleep(0.5)

        return True

    def switch_to_tasks_tab(self, emulator: Dict) -> bool:
        """Переключиться на вкладку 'Список дел'"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Переключение на 'Список дел'")
        tap(emulator, x=self.TAB_TASKS_COORDS[0], y=self.TAB_TASKS_COORDS[1])
        time.sleep(0.5)

        return True

    def collapse_all_sections(self, emulator: Dict, max_attempts: int = 15) -> bool:
        """
        Свернуть все развёрнутые разделы

        Алгоритм:
        1. Ищем стрелки "вниз" (развёрнутые разделы)
        2. Кликаем по самой верхней
        3. Повторяем пока не останется только стрелки "вправо"
        4. Должно быть ровно 7 стрелок "вправо"
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emulator_name}] Сворачивание всех разделов...")

        for attempt in range(1, max_attempts + 1):
            # Поиск стрелок "вниз" (основные разделы)
            arrow_down_coords = find_image(emulator, self.TEMPLATES['arrow_down'], threshold=0.8)

            # Поиск стрелок "вниз" (подвкладки)
            arrow_down_sub_coords = find_image(emulator, self.TEMPLATES['arrow_down_sub'], threshold=0.8)

            if arrow_down_coords is not None:
                # Есть развёрнутые основные разделы
                x, y = arrow_down_coords
                logger.debug(f"[{emulator_name}] Найдена стрелка вниз (основная) в ({x}, {y}), сворачиваем...")
                tap(emulator, x=int(x), y=int(y))
                time.sleep(0.8)

            elif arrow_down_sub_coords is not None:
                # Есть развёрнутые подвкладки
                x, y = arrow_down_sub_coords
                logger.debug(f"[{emulator_name}] Найдена стрелка вниз (подвкладка) в ({x}, {y}), сворачиваем...")
                tap(emulator, x=int(x), y=int(y))
                time.sleep(0.8)

            else:
                # Все разделы свёрнуты
                logger.success(f"[{emulator_name}] ✅ Все разделы свёрнуты (попыток: {attempt})")
                break

        if attempt >= max_attempts:
            logger.warning(f"[{emulator_name}] ⚠️ Достигнут лимит попыток ({max_attempts})")
            return False

        return True

    def execute_swipes(self, emulator: Dict, swipes: List[Dict]) -> bool:
        """
        Выполнить список свайпов из конфигурации

        Args:
            emulator: объект эмулятора
            swipes: список свайпов [{"direction": "down", "start_x": ..., ...}, ...]

        Returns:
            bool: True если все свайпы выполнены
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if not swipes:
            return True

        for swipe_data in swipes:
            direction = swipe_data.get('direction', 'down')
            start_x = swipe_data.get('start_x', 270)
            start_y = swipe_data.get('start_y', 700)
            end_x = swipe_data.get('end_x', 270)
            end_y = swipe_data.get('end_y', 300)
            duration = swipe_data.get('duration', 300)
            repeat = swipe_data.get('repeat', 1)

            for _ in range(repeat):
                swipe(emulator, x1=start_x, y1=start_y, x2=end_x, y2=end_y, duration=duration)
                logger.debug(f"[{emulator_name}] Свайп {direction}: ({start_x},{start_y}) → ({end_x},{end_y})")
                time.sleep(0.5)

        return True

    def navigate_to_building(self, emulator: Dict, building_name: str) -> bool:
        """
        Навигация к зданию с использованием конфигурации

        Полный процесс:
        1. Открыть панель навигации
        2. Выбрать правильную вкладку (Список дел / Список зданий)
        3. Свернуть все разделы
        4. Выполнить свайпы для доступа к разделу (если нужно)
        5. Открыть раздел
        6. Выполнить свайпы для доступа к подвкладке (если есть)
        7. Открыть подвкладку (если есть)
        8. Выполнить свайпы внутри подвкладки (если нужно)
        9. Найти здание через OCR
        10. Кликнуть "Перейти"

        Args:
            emulator: объект эмулятора
            building_name: название здания

        Returns:
            bool: True если успешно перешли к зданию
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emulator_name}] 🎯 Навигация к зданию: {building_name}")

        # 1. Получить конфигурацию здания
        building_config = self.get_building_config(building_name)
        if not building_config:
            logger.error(f"[{emulator_name}] ❌ Конфигурация здания не найдена")
            return False

        # 2. Открыть панель навигации
        if not self.open_navigation_panel(emulator):
            return False

        # 3. Выбрать вкладку
        if building_config.get('from_tasks_tab'):
            # Здание в "Список дел"
            self.switch_to_tasks_tab(emulator)
            time.sleep(0.5)

            # Найти через OCR и кликнуть "Перейти"
            screenshot = get_screenshot(emulator)
            if screenshot is None:
                return False

            # Используем статичные координаты из конфига
            button_coords = building_config.get('button_coords', {})
            x = button_coords.get('x', 330)
            y = button_coords.get('y', 390)

            logger.debug(f"[{emulator_name}] Клик 'Перейти' по координатам ({x}, {y})")
            tap(emulator, x=x, y=y)
            time.sleep(2)

            logger.success(f"[{emulator_name}] ✅ Перешли к зданию: {building_name}")
            return True

        else:
            # Здание в "Список зданий"
            self.switch_to_buildings_tab(emulator)
            time.sleep(0.5)

            # 4. Свернуть все разделы
            if not self.collapse_all_sections(emulator):
                logger.warning(f"[{emulator_name}] ⚠️ Не удалось свернуть все разделы")

            # 5. Свайпы для доступа к разделу (если нужно)
            section_data = building_config.get('section_data', {})
            if section_data.get('requires_scroll'):
                scroll_swipes = section_data.get('scroll_to_section', [])
                self.execute_swipes(emulator, scroll_swipes)

            # 6. Открыть раздел
            section_name = building_config.get('section')
            if not self._open_section_by_name(emulator, section_name):
                return False

            # 7. Работа с подвкладками (если есть)
            if 'subsection' in building_config:
                subsection_name = building_config['subsection']
                subsection_data = building_config.get('subsection_data', {})

                # Свайпы для доступа к подвкладке
                if subsection_data.get('requires_scroll'):
                    scroll_swipes = subsection_data.get('scroll_to_subsection', [])
                    self.execute_swipes(emulator, scroll_swipes)

                # Открыть подвкладку
                if not self._open_section_by_name(emulator, subsection_name):
                    return False

                # Свайпы внутри подвкладки
                scroll_swipes = building_config.get('scroll_in_subsection', [])
                self.execute_swipes(emulator, scroll_swipes)

            else:
                # Свайпы внутри секции (если нет подвкладок)
                scroll_swipes = building_config.get('scroll_in_section', [])
                self.execute_swipes(emulator, scroll_swipes)

            # 8. Найти здание через OCR и кликнуть "Перейти"
            return self._find_and_click_building(emulator, building_name, building_config)

    def _open_section_by_name(self, emulator: Dict, section_name: str) -> bool:
        """
        Открыть раздел/подвкладку по имени через OCR

        Args:
            emulator: объект эмулятора
            section_name: название раздела

        Returns:
            bool: True если раздел открыт
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Открытие раздела: {section_name}")

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        # Найти раздел через OCR
        elements = self.ocr.recognize_text(screenshot, min_confidence=0.5)

        for elem in elements:
            if section_name.lower() in elem['text'].lower():
                # Нашли раздел, кликаем
                tap(emulator, x=elem['x'], y=elem['y'])
                time.sleep(0.8)
                logger.debug(f"[{emulator_name}] ✅ Раздел '{section_name}' открыт")
                return True

        logger.warning(f"[{emulator_name}] ⚠️ Раздел '{section_name}' не найден на экране")
        return False

    def _find_and_click_building(self, emulator: Dict, building_name: str, building_config: Dict) -> bool:
        """
        Найти здание через OCR и кликнуть "Перейти"

        Args:
            emulator: объект эмулятора
            building_name: название здания
            building_config: конфигурация здания

        Returns:
            bool: True если успешно
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        emulator_id = emulator.get('id', 0)

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        # Парсинг через OCR
        buildings = self.ocr.parse_navigation_panel(screenshot, emulator_id=emulator_id)

        # Поиск нужного здания
        ocr_pattern = building_config.get('ocr_pattern', building_name)
        is_multiple = building_config.get('multiple', False)

        target_building = None

        for building in buildings:
            if ocr_pattern.lower() in building['name'].lower():
                # Нашли здание
                if is_multiple:
                    # Для множественных зданий - берем первое попавшееся
                    target_building = building
                    break
                else:
                    # Для уникальных - точное совпадение
                    target_building = building
                    break

        if not target_building:
            logger.error(f"[{emulator_name}] ❌ Здание '{building_name}' не найдено в списке")
            return False

        # Клик "Перейти"
        y_coord = target_building['y']
        tap(emulator, x=self.BUTTON_GO_X, y=y_coord)
        time.sleep(2)

        logger.success(f"[{emulator_name}] ✅ Перешли к зданию: {building_name} (Lv.{target_building['level']})")
        return True

    def reset_navigation_state(self, emulator: Dict) -> bool:
        """
        Сбросить состояние панели навигации

        Действия:
        1. Свернуть все подвкладки и разделы
        2. Свайп вверх 2 раза для возврата в начало
        3. Проверить что все свёрнуто

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если успешно
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Сброс состояния навигации...")

        # 1. Свернуть все разделы
        self.collapse_all_sections(emulator)

        # 2. Свайп вверх 2 раза
        metadata = self.config.get('metadata', {})
        scroll_to_top = metadata.get('scroll_to_top', [])
        self.execute_swipes(emulator, scroll_to_top)

        # 3. Еще раз проверить и свернуть
        self.collapse_all_sections(emulator)

        logger.debug(f"[{emulator_name}] ✅ Состояние навигации сброшено")
        return True