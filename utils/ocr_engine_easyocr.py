"""
Движок распознавания текста через EasyOCR (GPU)

Преимущества:
- Работает с CUDA 13.0
- Поддержка русского из коробки
- Быстрый на GPU (~0.5-1 сек)
"""

import os
import re
import cv2
import numpy as np
from datetime import datetime
from utils.logger import logger


class OCREngineEasyOCR:
    """
    Движок распознавания текста через EasyOCR

    Singleton: используйте get_ocr_engine_easyocr() для получения экземпляра
    """

    def __init__(self, gpu=True):
        """
        Инициализация EasyOCR

        Args:
            gpu: использовать GPU (True) или CPU (False)
        """
        try:
            import easyocr

            # Создать reader (загрузит модели при первом запуске)
            logger.info("Инициализация EasyOCR...")
            self.reader = easyocr.Reader(
                ['ru', 'en'],  # Русский + английский
                gpu=gpu
            )

            self.debug_mode = False
            self.gpu_enabled = gpu

            logger.success(f"OCREngineEasyOCR готов (GPU: {'ВКЛ' if gpu else 'ВЫКЛ'})")

        except ImportError as e:
            logger.error("EasyOCR не установлен!")
            logger.error("Установите: pip install easyocr")
            logger.error("И PyTorch: pip install torch --index-url https://download.pytorch.org/whl/cu118")
            raise
        except Exception as e:
            logger.error(f"Ошибка инициализации EasyOCR: {e}")
            raise

    def set_debug_mode(self, enabled):
        """Включает/выключает debug режим"""
        self.debug_mode = enabled
        logger.info(f"OCR debug режим: {'ВКЛ' if enabled else 'ВЫКЛ'}")

    def recognize_text(self, image, region=None, min_confidence=0.5):
        """
        Распознает текст на изображении

        ИЗМЕНЕНИЯ v1.1:
        - Добавлен детальный debug лог
        - Показывает ЧТО именно распознано
        """
        try:
            # Обрезать регион если указан
            if region:
                x1, y1, x2, y2 = region
                image = image[y1:y2, x1:x2].copy()

            # EasyOCR распознавание
            results = self.reader.readtext(image)

            if not results:
                logger.debug("EasyOCR не распознал текст на изображении")
                return []

            # ===== ДОБАВЛЕНО: Детальный лог =====
            logger.debug(f"EasyOCR raw результаты:")
            for i, (bbox, text, conf) in enumerate(results, 1):
                logger.debug(f"  {i}. '{text}' (conf: {conf:.2f})")
            # ====================================

            # Конвертировать в наш формат
            elements = []
            for bbox, text, conf in results:
                # Фильтр по confidence
                if conf < min_confidence:
                    continue

                # Вычислить центр bbox
                x_center = int((bbox[0][0] + bbox[2][0]) / 2)
                y_center = int((bbox[0][1] + bbox[2][1]) / 2)

                # Добавить смещение если был region
                if region:
                    x_center += region[0]
                    y_center += region[1]
                    bbox = [[p[0] + region[0], p[1] + region[1]] for p in bbox]

                elements.append({
                    'text': text.strip(),
                    'confidence': float(conf),
                    'bbox': bbox,
                    'x': x_center,
                    'y': y_center
                })

            logger.debug(f"EasyOCR распознал {len(elements)} элементов (порог: {min_confidence})")
            return elements

        except Exception as e:
            logger.error(f"Ошибка OCR распознавания: {e}")
            logger.exception(e)
            return []

    # ===== МЕТОДЫ ПАРСИНГА (КОПИРУЕМ ИЗ ocr_engine.py) =====

    def group_by_rows(self, elements, y_threshold=20):
        """Группирует элементы по строкам"""
        if not elements:
            return []

        sorted_elements = sorted(elements, key=lambda e: e['y'])

        rows = []
        current_row = [sorted_elements[0]]
        current_y = sorted_elements[0]['y']

        for element in sorted_elements[1:]:
            if abs(element['y'] - current_y) <= y_threshold:
                current_row.append(element)
            else:
                current_row.sort(key=lambda e: e['x'])
                rows.append(current_row)
                current_row = [element]
                current_y = element['y']

        if current_row:
            current_row.sort(key=lambda e: e['x'])
            rows.append(current_row)

        logger.debug(f"Элементы сгруппированы в {len(rows)} строк")
        return rows

    def parse_level(self, text):
        """
        Извлекает уровень из 'Lv.X' с учетом ошибок распознавания EasyOCR

        Поддерживаемые форматы:
        - "Lv.10" → стандарт (PaddleOCR)
        - "L10"   → EasyOCR (без точки и "v")
        - "L.10"  → EasyOCR (без "v")
        - "Lv 10" → EasyOCR (без точки, пробел)
        - "L .10" → EasyOCR (пробел перед точкой)
        - "L.g"   → EasyOCR (ошибка распознавания)

        Args:
            text: строка для парсинга

        Returns:
            int или None
        """
        # Паттерн 1: L + цифры (без точки и "v") - "L10"
        pattern1 = r'\bL(\d+)\b'
        match = re.search(pattern1, text, re.IGNORECASE)
        if match:
            level = int(match.group(1))
            logger.debug(f"Распознан уровень (паттерн L##): {level} из '{text}'")
            return level

        # Паттерн 2: L + точка + цифры (без "v") - "L.10"
        pattern2 = r'\bL\s*\.\s*(\d+)\b'
        match = re.search(pattern2, text, re.IGNORECASE)
        if match:
            level = int(match.group(1))
            logger.debug(f"Распознан уровень (паттерн L.##): {level} из '{text}'")
            return level

        # Паттерн 3: Lv + пробел + цифры - "Lv 10"
        pattern3 = r'\bL\s*v\s+(\d+)\b'
        match = re.search(pattern3, text, re.IGNORECASE)
        if match:
            level = int(match.group(1))
            logger.debug(f"Распознан уровень (паттерн Lv ##): {level} из '{text}'")
            return level

        # Паттерн 4: Стандартный Lv.X - "Lv.10"
        pattern4 = r'\bL\s*v\s*\.\s*(\d+)\b'
        match = re.search(pattern4, text, re.IGNORECASE)
        if match:
            level = int(match.group(1))
            logger.debug(f"Распознан уровень (паттерн Lv.##): {level} из '{text}'")
            return level

        # Паттерн 5: Ошибки OCR - "L.g" вместо "Lv.9"
        # Проверяем есть ли "L." и что-то похожее на цифру
        pattern5 = r'\bL\s*\.\s*([g9qo])\b'  # g→9, q→9, o→0
        match = re.search(pattern5, text, re.IGNORECASE)
        if match:
            char = match.group(1).lower()
            # Маппинг ошибок распознавания
            error_map = {'g': 9, 'q': 9, 'o': 0}
            level = error_map.get(char)
            if level is not None:
                logger.debug(f"Распознан уровень (паттерн L.{char}→{level}): {level} из '{text}'")
                return level

        return None

    def parse_timer(self, text):
        """Парсит таймер HH:MM:SS"""
        pattern = r'(\d{1,2}):(\d{2}):(\d{2})'
        match = re.search(pattern, text)

        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = int(match.group(3))

            if minutes > 59 or seconds > 59:
                return None

            total_seconds = hours * 3600 + minutes * 60 + seconds
            logger.debug(f"Распознан таймер: {text} = {total_seconds} сек")
            return total_seconds

        return None

    def parse_building_name(self, text):
        """
        Очищает название здания от 'Lv.X', 'L10', 'Перейти' и лишнего текста

        ИЗМЕНЕНИЯ v1.2:
        - Добавлена поддержка формата "L10" (без точки и "v")
        - Добавлена поддержка "L.10" (без "v")

        Args:
            text: строка для очистки

        Returns:
            str: очищенное название
        """
        # Удалить все варианты уровней
        text = re.sub(r'\bL\s*v\s*\.\s*\d+\b', '', text, flags=re.IGNORECASE)  # Lv.10
        text = re.sub(r'\bL\s*v\s+\d+\b', '', text, flags=re.IGNORECASE)  # Lv 10
        text = re.sub(r'\bL\s*\.\s*\d+\b', '', text, flags=re.IGNORECASE)  # L.10
        text = re.sub(r'\bL\d+\b', '', text, flags=re.IGNORECASE)  # L10
        text = re.sub(r'\bL\s*\.\s*[g9qo]\b', '', text, flags=re.IGNORECASE)  # L.g

        # Удалить "Перейти" и варианты
        text = re.sub(r'\bПерейти\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bПерсйти\b', '', text, flags=re.IGNORECASE)  # Ошибка OCR

        # Заменить переносы строк на пробел
        text = text.replace('\n', ' ')

        # Убрать лишние пробелы
        text = re.sub(r'\s+', ' ', text)

        # Strip
        return text.strip()

    def parse_navigation_panel(self, screenshot, emulator_id=None):
        """
        Парсит панель навигации

        ИЗМЕНЕНИЯ v1.4:
        - Двухпроходное распознавание (высокий + низкий confidence)
        - Debug скриншот ПОСЛЕ добавления всех элементов
        - Детальное логирование
        """
        logger.info("Парсинг панели навигации...")

        # ===== ПРОХОД 1: Высокий confidence (0.5) =====
        logger.debug("OCR Проход 1: min_confidence=0.5")
        elements_high = self.recognize_text(screenshot, min_confidence=0.5)
        logger.debug(f"OCR Проход 1: распознано {len(elements_high)} элементов")

        # ===== ПРОХОД 2: Низкий confidence (0.25) для уровней =====
        logger.debug("OCR Проход 2: min_confidence=0.25 (поиск пропущенных уровней)")
        elements_low = self.recognize_text(screenshot, min_confidence=0.25)
        logger.debug(f"OCR Проход 2: всего распознано {len(elements_low)} элементов")

        # Объединить: берем все из прохода 1, добавляем новые уровни из прохода 2
        elements = elements_high.copy()

        # Собрать уже существующие (текст, Y) для проверки дубликатов
        existing_data = {(elem['text'], elem['y']) for elem in elements}

        added_count = 0
        for elem in elements_low:
            text = elem['text']
            y_coord = elem['y']

            # Пропустить дубликаты
            if (text, y_coord) in existing_data:
                continue

            # Проверить похоже ли на уровень
            text_upper = text.upper()
            level_patterns = ['LV', 'L.', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8', 'L9', 'L0', 'LG', 'LQ', 'LO']

            is_level = any(pattern in text_upper for pattern in level_patterns)

            if is_level:
                elements.append(elem)
                added_count += 1
                logger.debug(f"  + Добавлен низкоконф уровень: '{text}' (conf: {elem['confidence']:.2f}, y: {y_coord})")

        logger.info(f"OCR Проход 2: добавлено {added_count} низкоконфиденс уровней")
        logger.info(f"OCR Итого элементов: {len(elements)}")

        if not elements:
            logger.warning("OCR не распознал элементы на панели навигации")
            return []

        # ===== DEBUG РЕЖИМ =====
        if self.debug_mode and emulator_id is not None:
            logger.debug("Сохранение debug скриншота...")
            try:
                self._save_debug_image(screenshot, elements, emulator_id, "navigation")
            except Exception as e:
                logger.error(f"Ошибка сохранения debug скриншота: {e}")
                logger.exception(e)

        # Группировка по строкам
        rows = self.group_by_rows(elements, y_threshold=20)

        # Парсинг каждой строки
        buildings = []
        building_counters = {}

        for i, row in enumerate(rows, 1):
            full_text = ' '.join([elem['text'] for elem in row])

            level = self.parse_level(full_text)
            building_name = self.parse_building_name(full_text)

            # Диагностика каждой строки
            logger.debug(f"Строка {i}: name='{building_name}', level={level}, raw='{full_text}'")

            if not building_name or level is None or len(building_name) < 3:
                continue

            y_coord = int(sum([elem['y'] for elem in row]) / len(row))

            if building_name not in building_counters:
                building_counters[building_name] = 0
            building_counters[building_name] += 1

            index = building_counters[building_name]
            button_coord = (330, y_coord)

            buildings.append({
                'name': building_name,
                'level': level,
                'index': index,
                'y_coord': y_coord,
                'button_coord': button_coord
            })

        logger.success(f"Распознано {len(buildings)} зданий")
        return buildings

    def _save_debug_image(self, image, elements, emulator_id, operation):
        """Сохраняет debug скриншот с bbox"""
        try:
            debug_folder = "data/screenshots/debug/ocr"
            os.makedirs(debug_folder, exist_ok=True)

            debug_img = image.copy()

            if not elements:
                cv2.putText(debug_img, "NO TEXT DETECTED", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            else:
                for elem in elements:
                    bbox = elem['bbox']
                    text = elem['text']
                    conf = elem['confidence']

                    # Цвет по confidence
                    color = (0, 255, 0) if conf >= 0.9 else (0, 255, 255) if conf >= 0.7 else (0, 0, 255)

                    # Рисовать bbox
                    points = np.array(bbox, dtype=np.int32)
                    cv2.polylines(debug_img, [points], True, color, 2)

                    # Текст
                    x, y = int(bbox[0][0]), int(bbox[0][1]) - 5
                    label = f"{text} ({conf:.2f})"

                    text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                    cv2.rectangle(debug_img, (x, y - text_size[1] - 5), (x + text_size[0], y), (0, 0, 0), -1)
                    cv2.putText(debug_img, label, (x, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"emu{emulator_id}_{operation}_{timestamp}.png"
            filepath = os.path.join(debug_folder, filename)

            cv2.imwrite(filepath, debug_img)
            logger.info(f"Debug скриншот: {os.path.abspath(filepath)}")

        except Exception as e:
            logger.error(f"Ошибка сохранения debug скриншота: {e}")


# ============================================
# Singleton
# ============================================

_ocr_easyocr_instance = None


def get_ocr_engine_easyocr():
    """Возвращает единственный экземпляр OCREngineEasyOCR (Singleton)"""
    global _ocr_easyocr_instance

    if _ocr_easyocr_instance is None:
        logger.info("Создание OCREngineEasyOCR (Singleton)...")
        _ocr_easyocr_instance = OCREngineEasyOCR(gpu=True)
        logger.success("OCREngineEasyOCR готов")

    return _ocr_easyocr_instance