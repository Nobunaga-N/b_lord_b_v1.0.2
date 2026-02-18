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

    # Разделы с одинаковыми иконками — навигация через OCR вместо шаблонов
    OCR_NAVIGATION_SECTIONS = {
        "Походный Отряд I",
        "Особый Отряд",
        "Поход Войска II",
        "Походный Отряд III",
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
    MAX_PATTERN = re.compile(r'[MМ][AА][XХ]', re.IGNORECASE)  # Латиница + Кириллица

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

        Для разделов с одинаковыми иконками (OCR_NAVIGATION_SECTIONS)
        используется OCR-поиск текста. Для остальных — template matching.

        Args:
            section_name: название раздела

        Returns:
            bool: True если раздел открыт
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Разделы с одинаковыми иконками → OCR-навигация
        if section_name in self.OCR_NAVIGATION_SECTIONS:
            logger.debug(f"[{emu_name}] OCR-навигация для раздела: {section_name}")
            return self._navigate_by_ocr(emulator, section_name)

        # Стандартная навигация через template matching
        template_path = self.SECTION_TEMPLATES.get(section_name)
        if not template_path or not os.path.exists(template_path):
            logger.error(f"[{emu_name}] ❌ Шаблон раздела не найден: {section_name}")
            return False

        logger.debug(f"[{emu_name}] Переход в раздел: {section_name}")

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

    # ==================== НОВЫЙ МЕТОД: OCR-навигация по разделам ====================

    # Вспомогательный паттерн для очистки текста (убирает не-буквы/не-цифры)
    _CLEAN_TEXT_PATTERN = re.compile(r'[^\w\s]', re.UNICODE)

    def _navigate_by_ocr(self, emulator: Dict, section_name: str) -> bool:
        """
        Найти и кликнуть по разделу через OCR-распознавание текста

        Для разделов с одинаковыми иконками (Походный Отряд I/III,
        Особый Отряд, Поход Войска II) — ищем текст названия на экране.

        Алгоритм:
        1. Скриншот экрана разделов
        2. OCR → получаем все текстовые элементы
        3. Склеиваем двухстрочные названия
        4. Ищем совпадение с section_name
        5. Кликаем чуть ВЫШЕ найденного текста (по иконке)

        Returns:
            bool: True если раздел найден и открыт
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Подготовка: нормализуем target
        target_clean = self._clean_for_comparison(section_name)

        for attempt in range(3):
            screenshot = get_screenshot(emulator)
            if screenshot is None:
                continue

            elements = self.ocr.recognize_text(screenshot, min_confidence=0.3)
            if not elements:
                time.sleep(0.5)
                continue

            # Склеиваем многострочные названия
            merged = self._merge_multiline_elements(elements)

            best_match = None
            best_ratio = 0.0

            for elem in merged:
                text_raw = self.ocr.normalize_cyrillic_text(elem['text'].strip())
                text_clean = self._clean_for_comparison(text_raw)

                # Точное совпадение (после очистки)
                if target_clean == text_clean:
                    best_match = elem
                    best_ratio = 1.0
                    break

                # Содержание
                if target_clean in text_clean or text_clean in target_clean:
                    ratio = min(len(target_clean), len(text_clean)) / \
                            max(len(target_clean), len(text_clean)) if text_clean else 0
                    if ratio > best_ratio and ratio > 0.6:
                        best_match = elem
                        best_ratio = ratio
                        continue

                # Нечёткое совпадение
                if len(target_clean) > 4 and len(text_clean) > 4:
                    common = sum(1 for a, b in zip(target_clean, text_clean) if a == b)
                    ratio = common / max(len(target_clean), len(text_clean))
                    if ratio > best_ratio and ratio > 0.7:
                        best_match = elem
                        best_ratio = ratio

            if best_match:
                click_x = best_match['x']
                click_y = best_match['y'] - 60  # Выше текста → по иконке

                if click_y < 50:
                    click_y = best_match['y']

                logger.debug(f"[{emu_name}] OCR нашёл '{section_name}' → "
                             f"OCR: '{best_match['text']}' (ratio={best_ratio:.2f}) "
                             f"Клик: ({click_x}, {click_y})")

                tap(emulator, x=click_x, y=click_y)
                time.sleep(2)
                logger.success(f"[{emu_name}] ✅ Раздел открыт (OCR): {section_name}")
                return True

            time.sleep(0.5)

        logger.error(f"[{emu_name}] ❌ Раздел не найден через OCR: {section_name}")
        return False

    @staticmethod
    def _clean_for_comparison(text: str) -> str:
        """
        Очистить текст для сравнения: убрать спецсимволы,
        привести к нижнему регистру, убрать пробелы

        "** Походный Отряд" → "походныйотряд"
        "Походный Отряд I" → "походныйотрядi"
        """
        # Убираем всё кроме букв, цифр и пробелов
        cleaned = re.sub(r'[^\w\s]', '', text, flags=re.UNICODE)
        # Убираем подчёркивания (они тоже \w)
        cleaned = cleaned.replace('_', '')
        # Нижний регистр, без пробелов
        return cleaned.lower().replace(' ', '')

    # ==================== НОВЫЙ МЕТОД: склейка многострочных элементов ====================

    def _merge_multiline_elements(self, elements: list,
                                   y_threshold: int = 30,
                                   x_threshold: int = 80) -> list:
        """
        Склеить OCR-элементы которые являются частями одного
        многострочного названия (например "Походный" + "Отряд I")

        Логика:
        - Сначала фильтрует мусор (звёзды, проценты, уровни)
        - Затем склеивает близкие текстовые элементы (до 2 строк)
        - Римские цифры (I, II, III, IV, V) не отбрасываются

        Args:
            elements: список OCR-элементов
            y_threshold: макс. расстояние по Y для склейки
            x_threshold: макс. расстояние центров по X

        Returns:
            Новый список элементов где многострочные склеены в один
        """
        if not elements:
            return []

        # Паттерны для фильтрации
        level_pattern = re.compile(r'^\d+\s*/\s*\d+$')
        max_pattern = re.compile(r'^[MМ][AА][XХ]$', re.IGNORECASE)  # Латиница + Кириллица
        percent_pattern = re.compile(r'^\d+%$')
        # Звёзды, спецсимволы — НЕ текст
        star_pattern = re.compile(r'^[\*★☆✫✯⭐✰\s\.·•●○◆◇■□▪▫]+$')
        # Римские цифры — СОХРАНЯЕМ (часть названий разделов/технологий)
        roman_pattern = re.compile(r'^[IVXivx]{1,4}$')

        # Разделяем на "текстовые" и "остальные"
        text_elements = []
        other_elements = []

        for elem in elements:
            txt = elem['text'].strip()

            # Мусор: уровни, MAX, проценты, звёзды
            if level_pattern.match(txt) or max_pattern.match(txt) or \
               percent_pattern.match(txt) or star_pattern.match(txt):
                other_elements.append(elem)
                continue

            # Короткий текст: пропускаем КРОМЕ римских цифр
            if len(txt) < 2 and not roman_pattern.match(txt):
                other_elements.append(elem)
                continue

            text_elements.append(elem)

        # Сортируем по Y, потом по X
        text_elements.sort(key=lambda e: (e['y'], e['x']))

        merged = []
        used = set()

        for i, elem_a in enumerate(text_elements):
            if i in used:
                continue

            # Ищем элемент для склейки (строкой ниже)
            group = [elem_a]
            used.add(i)

            for j, elem_b in enumerate(text_elements):
                if j in used or j == i:
                    continue

                # Проверяем близость по X (центры)
                x_diff = abs(elem_a['x'] - elem_b['x'])
                if x_diff > x_threshold:
                    continue

                # elem_b должен быть ниже elem_a и близко по Y
                y_diff = elem_b['y'] - elem_a['y']
                if 5 < y_diff < y_threshold:
                    group.append(elem_b)
                    used.add(j)
                    break  # Максимум 2 строки

            if len(group) == 1:
                merged.append(elem_a)
            else:
                # Склеиваем
                group.sort(key=lambda e: e['y'])
                combined_text = ' '.join(g['text'].strip() for g in group)

                # Координаты: X усредняем, Y берём от ВЕРХНЕГО элемента
                # (чтобы не сбить привязку уровень→название)
                avg_x = sum(g['x'] for g in group) // len(group)
                top_y = group[0]['y']  # ← Y верхнего элемента, не среднее!

                # Общий bbox
                x_min = min(g.get('x_min', g['x'] - 30) for g in group)
                y_min = min(g.get('y_min', g['y'] - 10) for g in group)
                x_max = max(g.get('x_max', g['x'] + 30) for g in group)
                y_max = max(g.get('y_max', g['y'] + 10) for g in group)

                merged.append({
                    'text': combined_text,
                    'x': avg_x,
                    'y': top_y,      # ← Y верхнего элемента
                    'x_min': x_min,
                    'y_min': y_min,
                    'x_max': x_max,
                    'y_max': y_max,
                    'confidence': min(g.get('confidence', 0.5) for g in group),
                    'merged': True,
                })

                logger.debug(f"🔗 Склеено: '{group[0]['text']}' + '{group[1]['text']}' "
                           f"→ '{combined_text}'")

        # Добавляем обратно "остальные" (уровни, MAX, звёзды)
        merged.extend(other_elements)

        return merged

    # ===== СВАЙПЫ ВНУТРИ РАЗДЕЛА =====

    def perform_swipes(self, emulator: Dict, swipe_config: Dict,
                       target_swipe_group: int):
        """
        Выполнить свайпы чтобы добраться до нужной группы технологий
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if target_swipe_group == 0:
            return

        # Свайп 1
        if target_swipe_group >= 1 and 'swipe_1' in swipe_config:
            coords = swipe_config['swipe_1']
            logger.debug(f"[{emu_name}] Свайп 1: ({coords[0]},{coords[1]}) → ({coords[2]},{coords[3]})")
            swipe(emulator, coords[0], coords[1], coords[2], coords[3],
                  duration=1200)  # ← БЫЛО 500
            time.sleep(2.0)      # ← БЫЛО 1

        # Свайп 2
        if target_swipe_group >= 2 and 'swipe_2' in swipe_config:
            coords = swipe_config['swipe_2']
            logger.debug(f"[{emu_name}] Свайп 2: ({coords[0]},{coords[1]}) → ({coords[2]},{coords[3]})")
            swipe(emulator, coords[0], coords[1], coords[2], coords[3],
                  duration=1200)  # ← БЫЛО 500
            time.sleep(2.0)      # ← БЫЛО 1

    # ===== OCR ПАРСИНГ УРОВНЕЙ =====

    def scan_tech_levels(self, emulator: Dict) -> List[Dict]:
        """
        Сканировать уровни технологий на текущем экране

        Распознаёт формат: "0/10", "3/5", "MAX"
        Привязывает уровень к названию по Y и X координатам.
        Поддерживает двухстрочные названия через склейку.

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

        # Склеиваем двухстрочные названия
        merged_elements = self._merge_multiline_elements(elements)

        # Разделяем на уровни и названия
        levels = []   # {'current': int, 'max': int, 'y': int, 'x': int}
        names = []    # {'text': str, 'y': int, 'x': int}

        for elem in merged_elements:
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
            cleaned = self.ocr.normalize_cyrillic_text(text)
            if len(cleaned) >= 3 and not cleaned.isdigit():
                names.append({'text': cleaned, 'y': y, 'x': x})

        logger.debug(f"[{emu_name}] OCR: найдено {len(levels)} уровней, {len(names)} названий")

        # Привязка: название находится НИЖЕ уровня
        # Учитываем и Y-расстояние, и X-расстояние для точной привязки
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
                if 5 < y_diff < 80:
                    # X-расстояние: название должно быть примерно под уровнем
                    x_diff = abs(name['x'] - lvl['x'])
                    if x_diff > 120:
                        continue  # Слишком далеко по горизонтали — другая технология

                    # Комбинированная дистанция (Y основной, X вспомогательный)
                    combined_dist = y_diff + x_diff * 0.3
                    if combined_dist < best_dist:
                        best_dist = combined_dist
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
        Поддерживает двухстрочные названия.

        Returns:
            (x, y) координаты названия для клика, или None
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        elements = self.ocr.recognize_text(screenshot, min_confidence=0.3)

        # Склеиваем двухстрочные названия
        merged = self._merge_multiline_elements(elements)

        # Нормализуем искомое имя
        target_lower = tech_name.lower().replace(' ', '')

        best_match = None
        best_ratio = 0.0

        for elem in merged:
            text = self.ocr.normalize_cyrillic_text(elem['text'].strip())
            text_lower = text.lower().replace(' ', '')

            # Точное совпадение
            if target_lower == text_lower:
                logger.debug(f"[{emu_name}] ✅ Найдена технология '{tech_name}' → "
                           f"OCR: '{text}' на ({elem['x']}, {elem['y']})")
                return (elem['x'], elem['y'])

            # Содержание
            if target_lower in text_lower or text_lower in target_lower:
                ratio = min(len(target_lower), len(text_lower)) / \
                        max(len(target_lower), len(text_lower))
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = elem

            # Нечёткое совпадение (>70%)
            if len(target_lower) > 4 and len(text_lower) > 4:
                common = sum(1 for a, b in zip(target_lower, text_lower) if a == b)
                ratio = common / max(len(target_lower), len(text_lower))
                if ratio > best_ratio and ratio > 0.7:
                    best_ratio = ratio
                    best_match = elem

        if best_match and best_ratio > 0.6:
            text = best_match['text'].strip()
            logger.debug(f"[{emu_name}] ✅ Найдена технология '{tech_name}' → "
                       f"OCR: '{text}' (ratio={best_ratio:.2f}) "
                       f"на ({best_match['x']}, {best_match['y']})")
            return (best_match['x'], best_match['y'])

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
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        all_techs = []

        for group in range(max_swipe_group + 1):
            if group > 0:
                swipe_key = f'swipe_{group}'
                if swipe_key in swipe_config:
                    coords = swipe_config[swipe_key]
                    swipe(emulator, coords[0], coords[1], coords[2], coords[3],
                          duration=1200)  # ← БЫЛО 500, стало 1200
                    time.sleep(2.0)      # ← БЫЛО 1.5, стало 2.0

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