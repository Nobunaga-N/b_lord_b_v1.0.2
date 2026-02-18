"""
Модуль исследования технологий Эволюции
Навигация по разделам, OCR парсинг уровней, запуск исследований

Версия: 1.0
Дата создания: 2025-02-18
"""

import os
import re
import time
from typing import Dict, List, Optional, Tuple
from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class EvolutionUpgrade:
    """
    Класс для исследования технологий Эволюции

    Процесс:
    1. Открыть окно Эволюции (иконка на главном экране)
    2. Перейти в нужный раздел (клик по шаблону)
    3. Найти технологию (свайпы + OCR)
    4. Кликнуть по технологии → обработать окно
    5. Парсинг таймера → запись в БД
    """

    # ===== ШАБЛОНЫ =====
    TEMPLATES = {
        # Иконка Эволюции на главном экране
        'evolution_icon': os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'evolution_icon.png'),

        # Кнопки в окне технологии
        'button_evolution': os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'button_evolution.png'),
        'button_refill': os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'button_refill_resources.png'),
        'button_confirm': os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'button_confirm.png'),
    }

    # Шаблоны разделов (section_name → путь к шаблону)
    SECTION_TEMPLATES = {
        "Развитие Территории": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'razvitie_territorii.png'),
        "Базовый Бой": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'bazovyj_boj.png'),
        "Средний Бой": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'srednij_boj.png'),
        "Особый Отряд": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'osobyj_otryad.png'),
        "Походный Отряд I": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'pokhodnyj_otryad_1.png'),
        "Поход Войска II": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'pokhod_vojska_2.png'),
        "Развитие Района": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'razvitie_rajona.png'),
        "Эволюция Плотоядных": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'evolyuciya_plotoyadnykh.png'),
        "Походный Отряд III": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'pokhodnyj_otryad_3.png'),
        "Эволюция Всеядных": os.path.join(BASE_DIR, 'data', 'templates', 'evolution', 'sections', 'evolyuciya_vseyadnykh.png'),
    }

    # Пороги для template matching
    THRESHOLD_ICON = 0.75
    THRESHOLD_BUTTON = 0.85
    THRESHOLD_SECTION = 0.80

    # Область парсинга таймера исследования (x1, y1, x2, y2)
    TIMER_AREA = (204, 467, 312, 517)

    # Максимум попыток найти иконку Эволюции
    MAX_ICON_ATTEMPTS = 3

    # Паттерны OCR для уровней
    LEVEL_PATTERN = re.compile(r'(\d+)\s*/\s*(\d+)')  # "0/10", "3/5"
    MAX_PATTERN = re.compile(r'MAX', re.IGNORECASE)

    def __init__(self):
        """Инициализация модуля"""
        self.ocr = OCREngine()

        # Проверяем шаблоны
        for name, path in self.TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "⚠️"
            logger.debug(f"{status} Шаблон '{name}': {path}")

        for name, path in self.SECTION_TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "⚠️"
            logger.debug(f"{status} Раздел '{name}': {path}")

        logger.info("✅ EvolutionUpgrade инициализирован")

    # ===== ОТКРЫТИЕ ОКНА ЭВОЛЮЦИИ =====

    def open_evolution_window(self, emulator: Dict) -> bool:
        """
        Открыть окно Эволюции через иконку на главном экране

        Обрабатывает случай когда вместо разделов открывается
        "левое окно" — ESC + повторный клик.

        Returns:
            bool: True если окно разделов открыто
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        for attempt in range(self.MAX_ICON_ATTEMPTS):
            logger.debug(f"[{emu_name}] Открытие окна Эволюции (попытка {attempt + 1})")

            # Ищем иконку Эволюции
            result = find_image(emulator, self.TEMPLATES['evolution_icon'],
                               threshold=self.THRESHOLD_ICON)

            if not result:
                if attempt == 0:
                    # Возможно какое-то окно мешает — делаем ресет
                    logger.warning(f"[{emu_name}] Иконка Эволюции не найдена, пробуем ресет...")
                    self._reset_to_main_screen(emulator)
                    time.sleep(1)
                    continue
                else:
                    logger.error(f"[{emu_name}] ❌ Иконка Эволюции не найдена")
                    return False

            center_x, center_y = result
            tap(emulator, x=center_x, y=center_y)
            time.sleep(2)

            # Проверяем — открылись ли разделы?
            # Пробуем найти любой известный раздел
            if self._verify_sections_visible(emulator):
                logger.success(f"[{emu_name}] ✅ Окно разделов Эволюции открыто")
                return True

            # Не нашли разделы — возможно "левое окно"
            logger.warning(f"[{emu_name}] ⚠️ Разделы не видны — закрываем левое окно...")
            press_key(emulator, "ESC")
            time.sleep(1)

        logger.error(f"[{emu_name}] ❌ Не удалось открыть окно Эволюции")
        return False

    def _verify_sections_visible(self, emulator: Dict) -> bool:
        """Проверить что видны разделы эволюции (хотя бы один шаблон)"""
        for section_name, path in self.SECTION_TEMPLATES.items():
            if not os.path.exists(path):
                continue
            result = find_image(emulator, path, threshold=self.THRESHOLD_SECTION)
            if result:
                return True
        return False

    def _reset_to_main_screen(self, emulator: Dict):
        """
        Ресет к главному экрану через многократное нажатие ESC

        Аналог технологии из строительства — вызывает окно выхода,
        потом ещё раз ESC чтобы его закрыть.
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        logger.debug(f"[{emu_name}] 🔄 Ресет к главному экрану...")

        for _ in range(8):
            press_key(emulator, "ESC")
            time.sleep(0.3)

        # Последний ESC закрывает окно "Выйти из игры?"
        time.sleep(0.5)
        press_key(emulator, "ESC")
        time.sleep(1)

    # ===== ПЕРЕХОД В РАЗДЕЛ =====

    def navigate_to_section(self, emulator: Dict, section_name: str) -> bool:
        """
        Перейти в нужный раздел эволюции

        Args:
            section_name: название раздела

        Returns:
            bool: True если раздел открыт
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        template_path = self.SECTION_TEMPLATES.get(section_name)
        if not template_path or not os.path.exists(template_path):
            logger.error(f"[{emu_name}] ❌ Шаблон раздела не найден: {section_name}")
            return False

        logger.debug(f"[{emu_name}] Переход в раздел: {section_name}")

        # Ищем и кликаем по шаблону раздела
        for attempt in range(3):
            result = find_image(emulator, template_path,
                               threshold=self.THRESHOLD_SECTION)
            if result:
                center_x, center_y = result
                tap(emulator, x=center_x, y=center_y)
                time.sleep(2)
                logger.success(f"[{emu_name}] ✅ Раздел открыт: {section_name}")
                return True

            time.sleep(0.5)

        logger.error(f"[{emu_name}] ❌ Раздел не найден: {section_name}")
        return False

    # ===== СВАЙПЫ ВНУТРИ РАЗДЕЛА =====

    def perform_swipes(self, emulator: Dict, swipe_config: Dict,
                       target_swipe_group: int):
        """
        Выполнить свайпы чтобы добраться до нужной группы технологий

        Args:
            swipe_config: конфигурация свайпов для раздела
            target_swipe_group: до какой группы нужно доскроллить (1 или 2)
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if target_swipe_group == 0:
            return  # Свайпы не нужны

        # Свайп 1
        if target_swipe_group >= 1 and 'swipe_1' in swipe_config:
            coords = swipe_config['swipe_1']
            logger.debug(f"[{emu_name}] Свайп 1: ({coords[0]},{coords[1]}) → ({coords[2]},{coords[3]})")
            swipe(emulator, coords[0], coords[1], coords[2], coords[3], duration=500)
            time.sleep(1)

        # Свайп 2
        if target_swipe_group >= 2 and 'swipe_2' in swipe_config:
            coords = swipe_config['swipe_2']
            logger.debug(f"[{emu_name}] Свайп 2: ({coords[0]},{coords[1]}) → ({coords[2]},{coords[3]})")
            swipe(emulator, coords[0], coords[1], coords[2], coords[3], duration=500)
            time.sleep(1)

    # ===== OCR ПАРСИНГ УРОВНЕЙ =====

    def scan_tech_levels(self, emulator: Dict) -> List[Dict]:
        """
        Сканировать уровни технологий на текущем экране

        Распознаёт формат: "0/10", "3/5", "MAX"
        Привязывает уровень к названию по Y-координатам.

        Returns:
            Список dict: [{'name': str, 'current_level': int, 'max_level': int, 'y': int}]
            Для MAX: current_level = -1 (сигнал что технология прокачана)
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            logger.error(f"[{emu_name}] ❌ Не удалось получить скриншот")
            return []

        # Распознаём весь текст
        elements = self.ocr.recognize_text(screenshot, min_confidence=0.3)

        if not elements:
            logger.warning(f"[{emu_name}] ⚠️ OCR не распознал текст")
            return []

        # Разделяем на уровни и названия
        levels = []   # {'current': int, 'max': int, 'y': int, 'x': int}
        names = []    # {'text': str, 'y': int, 'x': int}

        for elem in elements:
            text = elem['text'].strip()
            y = elem['y']
            x = elem['x']

            # Проверяем MAX
            if self.MAX_PATTERN.search(text):
                levels.append({'current': -1, 'max': -1, 'y': y, 'x': x})
                continue

            # Проверяем формат X/Y
            match = self.LEVEL_PATTERN.search(text)
            if match:
                current = int(match.group(1))
                max_lvl = int(match.group(2))
                levels.append({'current': current, 'max': max_lvl, 'y': y, 'x': x})
                continue

            # Всё остальное — потенциальное название технологии
            # Фильтруем мусор (слишком короткие, цифры)
            cleaned = self.ocr.normalize_cyrillic_text(text)
            if len(cleaned) >= 3 and not cleaned.isdigit():
                names.append({'text': cleaned, 'y': y, 'x': x})

        logger.debug(f"[{emu_name}] OCR: найдено {len(levels)} уровней, {len(names)} названий")

        # Привязка: название находится НИЖЕ уровня
        # Для каждого уровня ищем ближайшее название с Y > level.y
        results = []
        used_names = set()

        for lvl in sorted(levels, key=lambda l: l['y']):
            best_name = None
            best_dist = 999

            for i, name in enumerate(names):
                if i in used_names:
                    continue

                # Название должно быть НИЖЕ уровня (Y больше) и не слишком далеко
                y_diff = name['y'] - lvl['y']
                if 5 < y_diff < 80:  # От 5 до 80 пикселей ниже
                    if y_diff < best_dist:
                        best_dist = y_diff
                        best_name = (i, name['text'])

            if best_name:
                idx, text = best_name
                used_names.add(idx)
                results.append({
                    'name': text,
                    'current_level': lvl['current'],
                    'max_level': lvl['max'],
                    'y': lvl['y']
                })

        logger.info(f"[{emu_name}] 📊 Распознано технологий: {len(results)}")
        for r in results:
            lvl_str = "MAX" if r['current_level'] == -1 else f"{r['current_level']}/{r['max_level']}"
            logger.debug(f"[{emu_name}]   📍 {r['name']}: {lvl_str}")

        return results

    # ===== ПОИСК ТЕХНОЛОГИИ ПО ИМЕНИ =====

    def find_tech_on_screen(self, emulator: Dict,
                            tech_name: str) -> Optional[Tuple[int, int]]:
        """
        Найти технологию на экране по названию через OCR

        Returns:
            (x, y) координаты названия для клика, или None
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        elements = self.ocr.recognize_text(screenshot, min_confidence=0.3)

        # Нормализуем искомое имя
        target_lower = tech_name.lower().replace(' ', '')

        for elem in elements:
            text = self.ocr.normalize_cyrillic_text(elem['text'].strip())
            text_lower = text.lower().replace(' ', '')

            # Проверяем совпадение (допускаем частичное)
            if target_lower in text_lower or text_lower in target_lower:
                logger.debug(f"[{emu_name}] ✅ Найдена технология '{tech_name}' → "
                           f"OCR: '{text}' на ({elem['x']}, {elem['y']})")
                return (elem['x'], elem['y'])

            # Проверяем нечёткое совпадение (>70% символов)
            if len(target_lower) > 4:
                common = sum(1 for a, b in zip(target_lower, text_lower) if a == b)
                ratio = common / max(len(target_lower), len(text_lower))
                if ratio > 0.7:
                    logger.debug(f"[{emu_name}] ✅ Нечёткое совпадение '{tech_name}' → "
                               f"OCR: '{text}' (ratio={ratio:.2f})")
                    return (elem['x'], elem['y'])

        logger.warning(f"[{emu_name}] ⚠️ Технология не найдена на экране: {tech_name}")
        return None

    # ===== ИССЛЕДОВАНИЕ ТЕХНОЛОГИИ =====

    def research_tech(self, emulator: Dict, tech_name: str,
                      section_name: str,
                      swipe_config: Dict,
                      swipe_group: int) -> Tuple[str, Optional[int]]:
        """
        ГЛАВНЫЙ МЕТОД — исследовать технологию

        Процесс:
        1. Открыть окно Эволюции
        2. Перейти в раздел
        3. Свайпы если нужно
        4. Найти и кликнуть по технологии
        5. Обработать окно (Эволюция / Восполнить / Нет ресурсов)
        6. Парсинг таймера

        Args:
            emulator: объект эмулятора
            tech_name: название технологии
            section_name: раздел
            swipe_config: конфигурация свайпов
            swipe_group: группа свайпов (0, 1, 2)

        Returns:
            (status, timer_seconds):
            - ("started", 3600) — исследование начато
            - ("no_resources", None) — нет ресурсов → заморозка
            - ("error", None) — ошибка
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emu_name}] 🧬 Исследование: {tech_name} ({section_name})")

        # ШАГ 1: Открыть окно Эволюции
        if not self.open_evolution_window(emulator):
            return ("error", None)

        # ШАГ 2: Перейти в раздел
        if not self.navigate_to_section(emulator, section_name):
            self._close_evolution(emulator, esc_count=3)
            return ("error", None)

        # ШАГ 3: Свайпы если нужно
        self.perform_swipes(emulator, swipe_config, swipe_group)

        # ШАГ 4: Найти технологию на экране
        tech_coords = self.find_tech_on_screen(emulator, tech_name)
        if not tech_coords:
            logger.warning(f"[{emu_name}] ⚠️ Технология не найдена: {tech_name}")
            self._close_evolution(emulator, esc_count=3)
            return ("error", None)

        # ШАГ 5: Кликнуть по технологии
        tap(emulator, x=tech_coords[0], y=tech_coords[1])
        time.sleep(2)

        # ШАГ 6: Обработать окно
        result, timer = self._handle_tech_window(emulator)

        if result == "started":
            logger.success(f"[{emu_name}] ✅ Исследование начато: {tech_name}")
            # Закрываем окно эволюции (ESC×3)
            self._close_evolution(emulator, esc_count=3)
            return ("started", timer)

        elif result == "no_resources":
            logger.warning(f"[{emu_name}] ❌ Нехватка ресурсов для {tech_name}")
            # ESC×3 или ×4 в зависимости от варианта (уже обработано внутри)
            return ("no_resources", None)

        else:
            logger.error(f"[{emu_name}] ❌ Ошибка при исследовании {tech_name}")
            self._close_evolution(emulator, esc_count=3)
            return ("error", None)

    def _handle_tech_window(self, emulator: Dict) -> Tuple[str, Optional[int]]:
        """
        Обработать окно технологии после клика

        Варианты:
        1. Кнопка "Эволюция" — клик → парсинг таймера
        2. Кнопка "Восполнить Ресурсы" — клик → "Подтвердить" → парсинг таймера
           Если "Подтвердить" не найдена → ESC×4 → no_resources
        3. Нет ни одной кнопки → ESC×3 → no_resources

        Returns:
            (status, timer_seconds)
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ВАРИАНТ 1: Кнопка "Эволюция"
        result = find_image(emulator, self.TEMPLATES['button_evolution'],
                           threshold=self.THRESHOLD_BUTTON)
        if result:
            logger.debug(f"[{emu_name}] Найдена кнопка 'Эволюция'")
            center_x, center_y = result
            tap(emulator, x=center_x, y=center_y)
            time.sleep(2)

            # Парсинг таймера
            timer = self._parse_research_timer(emulator)
            return ("started", timer)

        # ВАРИАНТ 2: Кнопка "Восполнить Ресурсы"
        result = find_image(emulator, self.TEMPLATES['button_refill'],
                           threshold=self.THRESHOLD_BUTTON)
        if result:
            logger.debug(f"[{emu_name}] Найдена кнопка 'Восполнить Ресурсы'")
            center_x, center_y = result
            tap(emulator, x=center_x, y=center_y)
            time.sleep(2)

            # Ищем "Подтвердить"
            confirm_result = find_image(emulator, self.TEMPLATES['button_confirm'],
                                       threshold=self.THRESHOLD_BUTTON)
            if confirm_result:
                logger.debug(f"[{emu_name}] Найдена кнопка 'Подтвердить'")
                cx, cy = confirm_result
                tap(emulator, x=cx, y=cy)
                time.sleep(2)

                # Парсинг таймера
                timer = self._parse_research_timer(emulator)
                return ("started", timer)
            else:
                # "Подтвердить" не найдена — ресурса нет в рюкзаке
                logger.warning(f"[{emu_name}] ⚠️ Кнопка 'Подтвердить' не найдена — ресурсов нет")
                # ESC×4 чтобы полностью выйти
                self._close_evolution(emulator, esc_count=4)
                return ("no_resources", None)

        # ВАРИАНТ 3: Ни одной кнопки не найдено
        logger.warning(f"[{emu_name}] ⚠️ Не найдено ни 'Эволюция', ни 'Восполнить Ресурсы'")
        self._close_evolution(emulator, esc_count=3)
        return ("no_resources", None)

    def _parse_research_timer(self, emulator: Dict) -> Optional[int]:
        """
        Парсинг таймера исследования

        Область: TIMER_AREA (204, 467, 312, 517)
        Формат: "HH:MM:SS" или "D:HH:MM:SS"

        Returns:
            секунды или None
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        x1, y1, x2, y2 = self.TIMER_AREA

        # Парсим через OCR
        results = self.ocr.recognize_text(screenshot, region=(x1, y1, x2, y2),
                                          min_confidence=0.5)

        for elem in results:
            text = elem['text'].strip()

            # Формат D:HH:MM:SS
            match = re.search(r'(\d+):(\d{1,2}):(\d{2}):(\d{2})', text)
            if match:
                days = int(match.group(1))
                hours = int(match.group(2))
                minutes = int(match.group(3))
                seconds = int(match.group(4))
                total = days * 86400 + hours * 3600 + minutes * 60 + seconds
                logger.debug(f"[{emu_name}] ⏱️ Таймер: {text} = {total}с")
                return total

            # Формат HH:MM:SS
            match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})', text)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))
                total = hours * 3600 + minutes * 60 + seconds
                logger.debug(f"[{emu_name}] ⏱️ Таймер: {text} = {total}с")
                return total

        logger.warning(f"[{emu_name}] ⚠️ Не удалось спарсить таймер исследования")
        return None

    def _close_evolution(self, emulator: Dict, esc_count: int = 3):
        """Закрыть окно Эволюции через ESC"""
        for _ in range(esc_count):
            press_key(emulator, "ESC")
            time.sleep(0.5)

    # ===== ПЕРВИЧНОЕ СКАНИРОВАНИЕ =====

    def scan_section_levels(self, emulator: Dict, section_name: str,
                            swipe_config: Dict,
                            max_swipe_group: int) -> List[Dict]:
        """
        Сканировать уровни всех технологий в разделе

        Делает OCR для каждой swipe_group (0, 1, 2).

        Args:
            section_name: название раздела
            swipe_config: конфигурация свайпов
            max_swipe_group: максимальная группа свайпов в разделе

        Returns:
            Объединённый список всех технологий с уровнями
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        all_techs = []

        for group in range(max_swipe_group + 1):
            if group > 0:
                # Свайп для текущей группы
                swipe_key = f'swipe_{group}'
                if swipe_key in swipe_config:
                    coords = swipe_config[swipe_key]
                    swipe(emulator, coords[0], coords[1], coords[2], coords[3],
                          duration=500)
                    time.sleep(1.5)

            # OCR текущего экрана
            techs = self.scan_tech_levels(emulator)
            for t in techs:
                t['swipe_group'] = group
            all_techs.extend(techs)

        logger.info(f"[{emu_name}] 📊 Раздел '{section_name}': "
                   f"всего {len(all_techs)} технологий отсканировано")
        return all_techs

    # ===== УТИЛИТЫ =====

    @staticmethod
    def _format_time(seconds: int) -> str:
        """Форматировать секунды в читаемый вид"""
        if seconds < 60:
            return f"{seconds} сек"
        elif seconds < 3600:
            return f"{seconds // 60} мин"
        elif seconds < 86400:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h} ч {m} мин"
        else:
            d = seconds // 86400
            h = (seconds % 86400) // 3600
            return f"{d} д {h} ч"