"""
Панель навигации для строительства с УМНОЙ навигацией
Управление панелью быстрого доступа к зданиям

КЛЮЧЕВАЯ ОСОБЕННОСТЬ:
Состояние панели (открытые разделы/подвкладки) НЕ сбрасывается после клика "Перейти"
Сброс происходит ТОЛЬКО при перезапуске игры/эмулятора

Версия: 2.0 (SMART NAVIGATION)
Дата обновления: 2025-01-23
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


# ==================== КЛАСС СОСТОЯНИЯ НАВИГАЦИИ ====================
class NavigationState:
    """
    Отслеживает текущее состояние панели навигации

    ВАЖНО: Состояние НЕ сбрасывается при закрытии панели!
    Сброс только при перезапуске игры/эмулятора
    """

    def __init__(self):
        self.is_panel_open = False
        self.current_tab = None  # 'tasks' или 'buildings'
        self.current_section = None  # Например, "Ресурсы"
        self.current_subsection = None  # Например, "Песок"
        self.is_collapsed = False  # Все разделы свернуты?
        self.is_scrolled_to_top = False  # В начале списка?

    def reset(self):
        """
        ПОЛНЫЙ СБРОС - только при перезапуске игры
        """
        self.is_panel_open = False
        self.current_tab = None
        self.current_section = None
        self.current_subsection = None
        self.is_collapsed = False
        self.is_scrolled_to_top = False
        logger.debug("🔄 Состояние навигации ПОЛНОСТЬЮ сброшено")

    def close_panel(self):
        """
        Панель закрылась, но состояние разделов СОХРАНЯЕТСЯ
        """
        self.is_panel_open = False
        logger.debug("📱 Панель закрыта (состояние разделов сохранено)")

    def open_panel(self):
        """Панель открылась"""
        self.is_panel_open = True
        logger.debug("📱 Панель открыта")

    def set_tab(self, tab: str):
        """Установить текущую вкладку"""
        if self.current_tab != tab:
            # При смене вкладки - сбрасываем раздел/подраздел
            self.current_section = None
            self.current_subsection = None
            self.is_collapsed = False
            self.is_scrolled_to_top = False
        self.current_tab = tab
        logger.debug(f"📑 Вкладка: {tab}")

    def set_section(self, section: str, subsection: Optional[str] = None):
        """Установить текущий раздел и подвкладку"""
        self.current_section = section
        self.current_subsection = subsection
        if subsection:
            logger.debug(f"📂 Раздел: {section} > {subsection}")
        else:
            logger.debug(f"📂 Раздел: {section}")

    def mark_collapsed(self):
        """Отметить что все разделы свернуты"""
        self.is_collapsed = True
        logger.debug("📦 Все разделы свернуты")

    def mark_scrolled_to_top(self):
        """Отметить что проскроллили в начало"""
        self.is_scrolled_to_top = True
        logger.debug("⬆️ Проскроллено в начало")

    def is_in_same_location(self, target_tab: str, target_section: str,
                           target_subsection: Optional[str] = None) -> bool:
        """
        Проверить находимся ли уже в нужном месте
        """
        if self.current_tab != target_tab:
            return False
        if self.current_section != target_section:
            return False
        if target_subsection is not None:
            return self.current_subsection == target_subsection
        return self.current_subsection is None

    def get_state_info(self) -> str:
        """Получить текстовое представление состояния"""
        if not self.is_panel_open:
            info = "❌ Панель закрыта"
        else:
            info = f"✅ Панель открыта | Вкладка: {self.current_tab}"

        if self.current_section:
            info += f" | Раздел: {self.current_section}"
        if self.current_subsection:
            info += f" > {self.current_subsection}"

        flags = []
        if self.is_collapsed:
            flags.append("свернуто")
        if self.is_scrolled_to_top:
            flags.append("вверху")

        if flags:
            info += f" [{', '.join(flags)}]"

        return info


# ==================== ГЛАВНЫЙ КЛАСС ====================
class NavigationPanel:
    """
    Класс для работы с панелью навигации с УМНОЙ навигацией

    Оптимизации:
    - Не сворачивает разделы если уже в нужном месте
    - Не делает свайпы если не нужно
    - Запоминает состояние между открытиями панели
    """

    # Координаты
    PANEL_ICON_COORDS = (29, 481)
    TAB_TASKS_COORDS = (95, 252)
    TAB_BUILDINGS_COORDS = (291, 250)
    BUTTON_GO_X = 330
    BUILDING_CENTER = (268, 517)

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
        self.nav_state = NavigationState()  # НОВОЕ: Состояние навигации

        if not self.config:
            logger.error("❌ Не удалось загрузить конфигурацию building_navigation.yaml")
        else:
            logger.info("✅ Конфигурация building_navigation.yaml загружена")

        # Проверяем шаблоны
        for name, path in self.TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "❌"
            logger.debug(f"{status} Шаблон '{name}': {path}")

        logger.info("✅ NavigationPanel инициализирована (SMART MODE)")

    def _load_config(self) -> Optional[Dict]:
        """Загрузить конфигурацию из building_navigation.yaml"""
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
        """Получить конфигурацию здания из YAML"""
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
                    result = building.copy()
                    result['section'] = section_name
                    result['from_tasks_tab'] = False
                    return result

            # Проверяем подвкладки
            if section_data.get('has_subsections'):
                subsections = section_data.get('subsections', {})
                for subsection_name, subsection_data in subsections.items():
                    buildings = subsection_data.get('buildings', [])
                    for building in buildings:
                        if building['name'] == building_name:
                            result = building.copy()
                            result['section'] = section_name
                            result['subsection'] = subsection_name
                            result['subsection_data'] = subsection_data
                            result['from_tasks_tab'] = False
                            return result

        # Поиск в tasks_tab
        tasks_tab = self.config.get('tasks_tab', {})
        buildings = tasks_tab.get('buildings', [])
        for building in buildings:
            if building['name'] == building_name:
                result = building.copy()
                result['from_tasks_tab'] = True
                return result

        return None

    # ==================== БАЗОВЫЕ ОПЕРАЦИИ ====================

    def open_navigation_panel(self, emulator: Dict) -> bool:
        """Открыть панель навигации"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if self.nav_state.is_panel_open:
            logger.debug(f"[{emulator_name}] ✅ Панель уже открыта")
            return True

        logger.debug(f"[{emulator_name}] Открытие панели навигации...")
        tap(emulator, x=self.PANEL_ICON_COORDS[0], y=self.PANEL_ICON_COORDS[1])
        time.sleep(1.5)

        # Проверка что открылась
        if self.is_navigation_open(emulator):
            self.nav_state.open_panel()
            logger.success(f"[{emulator_name}] ✅ Панель навигации открыта")
            return True
        else:
            logger.error(f"[{emulator_name}] ❌ Не удалось открыть панель навигации")
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

        if self.nav_state.current_tab == 'buildings':
            logger.debug(f"[{emulator_name}] ✅ Уже на вкладке 'Список зданий'")
            return True

        logger.debug(f"[{emulator_name}] Переключение на 'Список зданий'")
        tap(emulator, x=self.TAB_BUILDINGS_COORDS[0], y=self.TAB_BUILDINGS_COORDS[1])
        time.sleep(0.5)

        self.nav_state.set_tab('buildings')
        return True

    def switch_to_tasks_tab(self, emulator: Dict) -> bool:
        """Переключиться на вкладку 'Список дел'"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if self.nav_state.current_tab == 'tasks':
            logger.debug(f"[{emulator_name}] ✅ Уже на вкладке 'Список дел'")
            return True

        logger.debug(f"[{emulator_name}] Переключение на 'Список дел'")
        tap(emulator, x=self.TAB_TASKS_COORDS[0], y=self.TAB_TASKS_COORDS[1])
        time.sleep(0.5)

        self.nav_state.set_tab('tasks')
        return True

    def collapse_all_sections(self, emulator: Dict, max_attempts: int = 20) -> bool:
        """
        Свернуть все развёрнутые разделы и подвкладки
        ПРИОРИТЕТ У ПОДВКЛАДОК!
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Сворачивание всех разделов...")

        for attempt in range(1, max_attempts + 1):
            # ПРИОРИТЕТ 1: Ищем подвкладки
            arrow_down_sub = find_image(emulator, self.TEMPLATES['arrow_down_sub'], threshold=0.8)

            if arrow_down_sub is not None:
                logger.debug(f"[{emulator_name}] Клик по подвкладке (стрелка вниз): {arrow_down_sub}")
                tap(emulator, x=arrow_down_sub[0], y=arrow_down_sub[1])
                time.sleep(0.5)
                continue

            # ПРИОРИТЕТ 2: Ищем основные разделы
            arrow_down = find_image(emulator, self.TEMPLATES['arrow_down'], threshold=0.8)

            if arrow_down is not None:
                logger.debug(f"[{emulator_name}] Клик по разделу (стрелка вниз): {arrow_down}")
                tap(emulator, x=arrow_down[0], y=arrow_down[1])
                time.sleep(0.5)
                continue

            # Ничего не найдено - всё свёрнуто
            logger.success(f"[{emulator_name}] ✅ Все разделы свёрнуты")
            self.nav_state.mark_collapsed()
            return True

        logger.warning(f"[{emulator_name}] ⚠️ Не удалось свернуть все разделы за {max_attempts} попыток")
        return False

    def execute_swipes(self, emulator: Dict, swipes: List[Dict]) -> bool:
        """Выполнить список свайпов"""
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

    def _open_section_by_name(self, emulator: Dict, section_name: str) -> bool:
        """Открыть раздел/подвкладку по имени через OCR"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Открытие раздела: {section_name}")

        # Получаем скриншот
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        # Распознаём текст
        elements = self.ocr.recognize_text(screenshot, min_confidence=0.3)

        # Нормализуем название для поиска
        section_normalized = section_name.lower().replace(' ', '')

        # Ищем раздел
        for elem in elements:
            text_normalized = elem['text'].lower().replace(' ', '')

            if section_normalized in text_normalized:
                # Нашли! Кликаем чуть правее текста (туда где стрелка)
                tap(emulator, x=elem['x'] + 50, y=elem['y'])
                time.sleep(0.5)

                logger.success(f"[{emulator_name}] ✅ Раздел '{section_name}' открыт")
                return True

        logger.error(f"[{emulator_name}] ❌ Раздел '{section_name}' не найден")
        return False

    def _find_and_click_building(self, emulator: Dict, building_name: str,
                                 building_config: Dict, building_index: Optional[int] = None) -> bool:
        """Найти здание через OCR и кликнуть 'Перейти'"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        emulator_id = emulator.get('id', 0)

        # Получаем скриншот
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        # Парсинг через OCR
        buildings = self.ocr.parse_navigation_panel(screenshot, emulator_id=emulator_id)

        if not buildings:
            logger.error(f"[{emulator_name}] ❌ Не удалось распознать здания")
            return False

        # Ищем нужное здание
        ocr_pattern = building_config.get('ocr_pattern', building_name)
        is_multiple = building_config.get('multiple', False)

        ocr_pattern_normalized = ocr_pattern.lower().replace(' ', '')

        if is_multiple and building_index is not None:
            # Множественные здания - ищем по индексу
            matching_buildings = []

            for building in buildings:
                building_name_normalized = building['name'].lower().replace(' ', '')
                if ocr_pattern_normalized in building_name_normalized:
                    matching_buildings.append(building)

            if not matching_buildings:
                logger.error(f"[{emulator_name}] ❌ Здание не найдено")
                return False

            # Сортируем по Y (сверху вниз)
            matching_buildings.sort(key=lambda b: b['y'])

            if building_index > len(matching_buildings):
                logger.error(f"[{emulator_name}] ❌ Индекс {building_index} вне диапазона")
                return False

            target_building = matching_buildings[building_index - 1]
        else:
            # Уникальное здание
            target_building = None
            for building in buildings:
                building_name_normalized = building['name'].lower().replace(' ', '')
                if ocr_pattern_normalized in building_name_normalized:
                    target_building = building
                    break

            if not target_building:
                logger.error(f"[{emulator_name}] ❌ Здание не найдено")
                return False

        # Кликаем "Перейти"
        go_button_y = target_building['y']
        tap(emulator, x=self.BUTTON_GO_X, y=go_button_y)
        time.sleep(2)

        logger.success(f"[{emulator_name}] ✅ Перешли к зданию: {target_building['name']} Lv.{target_building['level']}")

        # ВАЖНО: Панель закрылась, но состояние СОХРАНЕНО
        self.nav_state.close_panel()

        return True

    # ==================== УМНАЯ НАВИГАЦИЯ ====================

    def navigate_to_building(self, emulator: Dict, building_name: str,
                            building_index: Optional[int] = None) -> bool:
        """
        УМНАЯ навигация к зданию

        Оптимизации:
        - Пропускает сворачивание если уже в нужном месте
        - Не делает лишние свайпы
        - Использует кэш состояния навигации

        Args:
            emulator: объект эмулятора
            building_name: название здания
            building_index: индекс (для множественных)

        Returns:
            bool: True если успешно
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emulator_name}] 🎯 Навигация: {building_name}" +
                   (f" #{building_index}" if building_index else ""))
        logger.debug(f"[{emulator_name}] 📊 {self.nav_state.get_state_info()}")

        # 1. Получить конфигурацию здания
        building_config = self.get_building_config(building_name)
        if not building_config:
            logger.error(f"[{emulator_name}] ❌ Конфигурация не найдена")
            return False

        # 2. Открыть панель если закрыта
        if not self.nav_state.is_panel_open:
            if not self.open_navigation_panel(emulator):
                return False

        # 3. Определяем тип навигации
        from_tasks_tab = building_config.get('from_tasks_tab', False)

        if from_tasks_tab:
            # === НАВИГАЦИЯ ЧЕРЕЗ "СПИСОК ДЕЛ" ===
            return self._navigate_via_tasks_tab(emulator, building_config)
        else:
            # === НАВИГАЦИЯ ЧЕРЕЗ "СПИСОК ЗДАНИЙ" ===
            return self._navigate_via_buildings_tab(emulator, building_config, building_index)

    def _navigate_via_tasks_tab(self, emulator: Dict, building_config: Dict) -> bool:
        """Навигация через 'Список дел'"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Переключаемся на вкладку
        self.switch_to_tasks_tab(emulator)
        time.sleep(0.5)

        # Используем статичные координаты
        button_coords = building_config.get('button_coords', {})
        x = button_coords.get('x', 330)
        y = button_coords.get('y', 390)

        tap(emulator, x=x, y=y)
        time.sleep(2)

        # Панель закрылась, состояние сохранено
        self.nav_state.close_panel()

        logger.success(f"[{emulator_name}] ✅ Перешли к зданию")
        return True

    def _navigate_via_buildings_tab(self, emulator: Dict, building_config: Dict,
                                   building_index: Optional[int]) -> bool:
        """Навигация через 'Список зданий' с ОПТИМИЗАЦИЕЙ"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # 1. Переключаемся на вкладку "Список зданий"
        self.switch_to_buildings_tab(emulator)
        time.sleep(0.5)

        # 2. Получаем целевой раздел и подвкладку
        target_section = building_config.get('section')
        target_subsection = building_config.get('subsection')

        # 3. ПРОВЕРКА: Может мы уже в нужном месте?
        if self.nav_state.is_in_same_location('buildings', target_section, target_subsection):
            logger.success(f"[{emulator_name}] 🚀 УЖЕ В НУЖНОМ РАЗДЕЛЕ!")
            logger.debug(f"[{emulator_name}] ⚡ Пропускаем навигацию, сразу ищем здание")

            # Сразу ищем здание на экране
            return self._find_and_click_building(emulator, building_config.get('name'),
                                                building_config, building_index)

        # 4. Нужна навигация - определяем тип
        needs_full_reset = self._check_needs_full_reset(target_section, target_subsection)

        if needs_full_reset:
            logger.debug(f"[{emulator_name}] 🔄 Полная навигация (смена раздела)")

            # Сворачиваем всё если еще не свернуто
            if not self.nav_state.is_collapsed:
                self.collapse_all_sections(emulator)

            # Свайпы вверх если еще не в начале
            if not self.nav_state.is_scrolled_to_top:
                metadata = self.config.get('metadata', {})
                scroll_to_top = metadata.get('scroll_to_top', [])
                self.execute_swipes(emulator, scroll_to_top)
                self.nav_state.mark_scrolled_to_top()
        else:
            logger.debug(f"[{emulator_name}] ⚡ Частичная навигация (тот же раздел)")

        # 5. Открываем целевой раздел
        if not self._open_section_by_name(emulator, target_section):
            logger.error(f"[{emulator_name}] ❌ Не удалось открыть раздел: {target_section}")
            return False

        time.sleep(0.5)

        # 6. Работа с подвкладками
        if target_subsection:
            subsection_data = building_config.get('subsection_data', {})

            # Свайпы для доступа к подвкладке
            if subsection_data.get('requires_scroll'):
                scroll_swipes = subsection_data.get('scroll_to_subsection', [])
                self.execute_swipes(emulator, scroll_swipes)
                time.sleep(0.3)

            # Открываем подвкладку
            if not self._open_section_by_name(emulator, target_subsection):
                logger.error(f"[{emulator_name}] ❌ Не удалось открыть подвкладку: {target_subsection}")
                return False

            time.sleep(0.5)

            # Свайпы внутри подвкладки
            scroll_swipes = building_config.get('scroll_in_subsection', [])
            self.execute_swipes(emulator, scroll_swipes)
            time.sleep(0.3)
        else:
            # Свайпы внутри основного раздела
            scroll_swipes = building_config.get('scroll_in_section', [])
            self.execute_swipes(emulator, scroll_swipes)
            time.sleep(0.3)

        # 7. Обновляем состояние навигации
        self.nav_state.set_section(target_section, target_subsection)

        # 8. Находим и кликаем на здание
        return self._find_and_click_building(emulator, building_config.get('name'),
                                            building_config, building_index)

    def _check_needs_full_reset(self, target_section: str,
                               target_subsection: Optional[str]) -> bool:
        """
        Проверить нужен ли полный сброс навигации

        Полный сброс НЕ нужен если:
        - Остаемся в том же разделе
        - Для "Ресурсы": та же подвкладка
        - Для "Развитие": между Жилище Детенышей ↔ Зона Кормления
        - Для "Битва": между Логово Всеядных ↔ Логово Плотоядных
        """
        current_section = self.nav_state.current_section
        current_subsection = self.nav_state.current_subsection

        # Раздел не совпадает - нужен полный сброс
        if current_section != target_section:
            return True

        # === ВКЛАДКА "РЕСУРСЫ" ===
        if target_section == "Ресурсы":
            # Если подвкладка та же - НЕ нужен сброс
            if current_subsection == target_subsection:
                return False
            # Разные подвкладки - нужен сброс
            return True

        # === ВКЛАДКА "РАЗВИТИЕ" ===
        if target_section == "Развитие":
            # Для группы "Жилище Детенышей" + "Зона Кормления" можно не сбрасывать
            # НО это требует дополнительной информации о текущем здании
            # Пока для безопасности - ВСЕГДА сброс
            return True

        # === ВКЛАДКА "БИТВА" ===
        if target_section == "Битва":
            # Для "Логово Всеядных" + "Логово Плотоядных" можно не сбрасывать
            # Пока для безопасности - ВСЕГДА сброс
            return True

        # Для всех остальных - полный сброс
        return True

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    def reset_navigation_state(self, emulator: Dict) -> bool:
        """
        УСТАРЕВШИЙ метод - оставлен для совместимости
        Используй навигацию через navigate_to_building() вместо этого
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Сброс состояния навигации (legacy)...")

        # Сворачиваем всё
        self.collapse_all_sections(emulator)

        # Свайпы вверх
        metadata = self.config.get('metadata', {})
        scroll_to_top = metadata.get('scroll_to_top', [])
        self.execute_swipes(emulator, scroll_to_top)

        # Обновляем состояние
        self.nav_state.mark_collapsed()
        self.nav_state.mark_scrolled_to_top()

        return True

    def get_building_level(self, emulator: Dict, building_name: str,
                          building_index: Optional[int] = None) -> Optional[int]:
        """
        Получить уровень здания БЕЗ перехода к нему
        Используется для первичного сканирования
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        emulator_id = emulator.get('id', 0)

        logger.info(f"[{emulator_name}] 🔍 Сканирование уровня: {building_name}" +
                   (f" #{building_index}" if building_index else ""))

        # Получить конфигурацию
        building_config = self.get_building_config(building_name)
        if not building_config:
            logger.error(f"[{emulator_name}] ❌ Конфигурация не найдена")
            return None

        # Открыть панель
        if not self.open_navigation_panel(emulator):
            return None

        # Навигация к разделу (но НЕ кликать "Перейти")
        if building_config.get('from_tasks_tab'):
            self.switch_to_tasks_tab(emulator)
            time.sleep(0.5)
        else:
            self.switch_to_buildings_tab(emulator)
            time.sleep(0.5)

            # Полная навигация к разделу
            if not self.nav_state.is_collapsed:
                self.collapse_all_sections(emulator)

            if not self.nav_state.is_scrolled_to_top:
                metadata = self.config.get('metadata', {})
                scroll_to_top = metadata.get('scroll_to_top', [])
                self.execute_swipes(emulator, scroll_to_top)
                self.nav_state.mark_scrolled_to_top()

            section_name = building_config.get('section')
            if not self._open_section_by_name(emulator, section_name):
                return None

            if 'subsection' in building_config:
                subsection_name = building_config['subsection']
                subsection_data = building_config.get('subsection_data', {})

                if subsection_data.get('requires_scroll'):
                    scroll_swipes = subsection_data.get('scroll_to_subsection', [])
                    self.execute_swipes(emulator, scroll_swipes)

                if not self._open_section_by_name(emulator, subsection_name):
                    return None

                scroll_swipes = building_config.get('scroll_in_subsection', [])
                self.execute_swipes(emulator, scroll_swipes)
            else:
                scroll_swipes = building_config.get('scroll_in_section', [])
                self.execute_swipes(emulator, scroll_swipes)

        # Получить скриншот и парсить
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        buildings = self.ocr.parse_navigation_panel(screenshot, emulator_id=emulator_id)

        if not buildings:
            logger.warning(f"[{emulator_name}] ⚠️ Не удалось распознать здания")
            return None

        # Найти нужное здание
        ocr_pattern = building_config.get('ocr_pattern', building_name)
        is_multiple = building_config.get('multiple', False)

        ocr_pattern_normalized = ocr_pattern.lower().replace(' ', '')

        if is_multiple and building_index is not None:
            matching_buildings = []

            for building in buildings:
                building_name_normalized = building['name'].lower().replace(' ', '')
                if ocr_pattern_normalized in building_name_normalized:
                    matching_buildings.append(building)

            if not matching_buildings:
                logger.error(f"[{emulator_name}] ❌ Здание не найдено")
                return None

            matching_buildings.sort(key=lambda b: b['y'])

            if building_index > len(matching_buildings):
                logger.error(f"[{emulator_name}] ❌ Индекс вне диапазона")
                return None

            target_building = matching_buildings[building_index - 1]
            level = target_building['level']

            logger.success(f"[{emulator_name}] ✅ {building_name} #{building_index}: Lv.{level}")
            return level
        else:
            for building in buildings:
                building_name_normalized = building['name'].lower().replace(' ', '')
                if ocr_pattern_normalized in building_name_normalized:
                    level = building['level']
                    logger.success(f"[{emulator_name}] ✅ {building['name']}: Lv.{level}")
                    return level

        logger.error(f"[{emulator_name}] ❌ Здание не найдено")
        return None

    def get_all_testable_buildings(self) -> List[Dict]:
        """Получить список всех testable зданий из конфигурации"""
        testable = []

        if not self.config:
            return testable

        navigation = self.config.get('navigation', {})
        sections = navigation.get('sections', {})

        for section_name, section_data in sections.items():
            buildings = section_data.get('buildings', [])
            for building in buildings:
                if building.get('testable', False):
                    building['section'] = section_name
                    building['from_tasks_tab'] = False
                    testable.append(building.copy())

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

        tasks_tab = self.config.get('tasks_tab', {})
        buildings = tasks_tab.get('buildings', [])
        for building in buildings:
            if building.get('testable', False):
                building['from_tasks_tab'] = True
                testable.append(building.copy())

        logger.info(f"📊 Найдено testable зданий: {len(testable)}")
        return testable