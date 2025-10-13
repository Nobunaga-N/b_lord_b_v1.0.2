"""
Движок распознавания текста через PaddleOCR
"""

import os
import re
import cv2
import numpy as np
from datetime import datetime
from paddleocr import PaddleOCR
from utils.logger import logger


class OCREngine:
    """
    Движок распознавания текста через PaddleOCR

    Возможности:
    - Распознавание русского и английского текста
    - Построчная группировка элементов
    - Парсинг уровней зданий (Lv.X)
    - Парсинг таймеров (HH:MM:SS)
    - Парсинг названий зданий
    - Debug режим (сохранение изображений с bbox)

    Singleton: используйте get_ocr_engine() для получения экземпляра
    """

    def __init__(self, lang='ru'):
        """
        Инициализация PaddleOCR

        Args:
            lang: Язык распознавания ('ru' включает латиницу)
        """
        try:
            # Минимальная инициализация (совместимость с разными версиями PaddleOCR)
            self.ocr = PaddleOCR(lang=lang)
            self.debug_mode = False
            logger.info("OCREngine инициализирован (PaddleOCR)")

        except Exception as e:
            logger.error(f"Ошибка инициализации PaddleOCR: {e}")
            raise

    def set_debug_mode(self, enabled):
        """
        Включает/выключает debug режим

        Args:
            enabled: True для включения, False для выключения
        """
        self.debug_mode = enabled
        logger.info(f"OCR debug режим: {'ВКЛ' if enabled else 'ВЫКЛ'}")

    def recognize_text(self, image, region=None, min_confidence=0.5):
        """
        Распознает текст на изображении

        Args:
            image: numpy.ndarray (BGR формат OpenCV)
            region: tuple (x1, y1, x2, y2) - область для OCR (опционально)
            min_confidence: минимальный порог уверенности (0.0-1.0)

        Returns:
            list: Список распознанных элементов
            [
                {
                    'text': 'Ферма Грунта',
                    'confidence': 0.98,
                    'bbox': [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
                    'x': x_center,
                    'y': y_center
                },
                ...
            ]
        """
        try:
            # Обрезать регион если указан
            if region:
                x1, y1, x2, y2 = region
                image = image[y1:y2, x1:x2]

            # OCR распознавание (без параметра cls для совместимости)
            result = self.ocr.ocr(image)

            # Debug: вывести структуру результата
            logger.debug(f"OCR result type: {type(result)}")
            logger.debug(f"OCR result length: {len(result) if result else 0}")
            if result and len(result) > 0:
                logger.debug(f"OCR result[0] type: {type(result[0])}")
                logger.debug(f"OCR result[0] length: {len(result[0]) if result[0] else 0}")
                if result[0] and len(result[0]) > 0:
                    logger.debug(f"OCR first line structure: {result[0][0]}")

            if not result or not result[0]:
                logger.debug("OCR не распознал текст на изображении")
                return []

            # Форматирование результатов (с защитой от разных форматов)
            elements = []
            for line in result[0]:
                try:
                    # Попытка 1: Стандартный формат [bbox, (text, confidence)]
                    bbox = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]

                    # Проверка формата второго элемента
                    if isinstance(line[1], (list, tuple)) and len(line[1]) >= 2:
                        text = line[1][0]
                        confidence = line[1][1]
                    elif isinstance(line[1], str):
                        # Возможно только текст, без confidence
                        text = line[1]
                        confidence = 1.0  # По умолчанию
                    else:
                        logger.warning(f"Неожиданный формат line[1]: {line[1]}")
                        continue

                    # Фильтр по confidence
                    if confidence < min_confidence:
                        continue

                    # Вычислить центр bbox
                    x_center = int((bbox[0][0] + bbox[2][0]) / 2)
                    y_center = int((bbox[0][1] + bbox[2][1]) / 2)

                    # Добавить смещение если был region
                    if region:
                        x_center += region[0]
                        y_center += region[1]
                        # Обновить bbox с учетом смещения
                        bbox = [[p[0] + region[0], p[1] + region[1]] for p in bbox]

                    elements.append({
                        'text': str(text).strip(),
                        'confidence': float(confidence),
                        'bbox': bbox,
                        'x': x_center,
                        'y': y_center
                    })

                except Exception as e:
                    logger.warning(f"Ошибка обработки OCR строки: {e}")
                    logger.debug(f"Проблемная строка: {line}")
                    continue

            logger.debug(f"OCR распознал {len(elements)} элементов (порог: {min_confidence})")
            return elements

        except Exception as e:
            logger.error(f"Ошибка OCR распознавания: {e}")
            logger.exception(e)
            return []

    def group_by_rows(self, elements, y_threshold=20):
        """
        Группирует элементы по строкам на основе Y-координат

        Алгоритм:
        1. Сортируем элементы по Y (сверху вниз)
        2. Первый элемент = начало первой строки
        3. Для каждого следующего:
           - Если |Y_current - Y_row| <= threshold → добавляем в строку
           - Иначе → создаем новую строку
        4. Внутри строки сортируем по X (слева направо)

        Args:
            elements: список элементов из recognize_text()
            y_threshold: максимальная разница по Y для одной строки (пикселей)

        Returns:
            list: Список строк
            [
                [элемент1, элемент2],  # Строка 1
                [элемент3, элемент4],  # Строка 2
                ...
            ]
        """
        if not elements:
            return []

        # Сортировка по Y (сверху вниз)
        sorted_elements = sorted(elements, key=lambda e: e['y'])

        rows = []
        current_row = [sorted_elements[0]]
        current_y = sorted_elements[0]['y']

        # Группировка
        for element in sorted_elements[1:]:
            if abs(element['y'] - current_y) <= y_threshold:
                # Добавляем в текущую строку
                current_row.append(element)
            else:
                # Начинаем новую строку
                # Сортируем текущую строку по X (слева направо)
                current_row.sort(key=lambda e: e['x'])
                rows.append(current_row)

                # Новая строка
                current_row = [element]
                current_y = element['y']

        # Добавить последнюю строку
        if current_row:
            current_row.sort(key=lambda e: e['x'])
            rows.append(current_row)

        logger.debug(f"Элементы сгруппированы в {len(rows)} строк (threshold: {y_threshold}px)")
        return rows

    def parse_level(self, text):
        """
        Извлекает уровень из текста 'Lv.X'

        Примеры:
            'Lv.1' → 1
            'Ферма Грунта Lv.12' → 12
            'Lv. 1' → 1 (пробел после точки)
            'L v.1' → 1 (пробел в середине)
            'Lv .10' → 10 (пробел перед точкой)

        Args:
            text: строка для парсинга

        Returns:
            int или None
        """
        # Regex с учетом возможных пробелов (ошибки OCR)
        # L\s*v\s*\.\s*(\d+) = L (пробелы) v (пробелы) . (пробелы) цифры
        pattern = r'L\s*v\s*\.\s*(\d+)'
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            level = int(match.group(1))
            logger.debug(f"Распознан уровень: {level} из '{text}'")
            return level

        return None

    def parse_timer(self, text):
        """
        Парсит таймер HH:MM:SS и конвертирует в секунды

        Примеры:
            '08:33:05' → 8*3600 + 33*60 + 5 = 30785 секунд
            '1:30:45' → 1*3600 + 30*60 + 45 = 5445 секунд
            '00:05:00' → 300 секунд

        Args:
            text: строка с таймером

        Returns:
            int (секунды) или None
        """
        # Regex: HH:MM:SS (часы могут быть 1-2 цифры)
        pattern = r'(\d{1,2}):(\d{2}):(\d{2})'
        match = re.search(pattern, text)

        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = int(match.group(3))

            # Валидация
            if minutes > 59 or seconds > 59:
                logger.warning(f"Некорректный таймер: {text} (минуты или секунды >59)")
                return None

            total_seconds = hours * 3600 + minutes * 60 + seconds
            logger.debug(f"Распознан таймер: {text} = {total_seconds} секунд")
            return total_seconds

        return None

    def parse_building_name(self, text):
        """
        Очищает название здания от 'Lv.X' и лишнего текста

        Примеры:
            'Ферма Грунта Lv.1' → 'Ферма Грунта'
            '  Склад Грунта  Lv.7  ' → 'Склад Грунта'
            'Ферма\nГрунта Lv.5' → 'Ферма Грунта'

        Args:
            text: строка для очистки

        Returns:
            str: очищенное название
        """
        # Удалить ' Lv.X' (с пробелом перед)
        text = re.sub(r'\s+L\s*v\s*\.\s*\d+', '', text, flags=re.IGNORECASE)

        # Заменить переносы строк на пробел
        text = text.replace('\n', ' ')

        # Убрать лишние пробелы
        text = re.sub(r'\s+', ' ', text)

        # Strip
        text = text.strip()

        return text

    def parse_navigation_panel(self, screenshot, emulator_id=None):
        """
        Парсит панель навигации с привязкой название ↔ уровень ↔ индекс

        Алгоритм:
        1. OCR всего скриншота
        2. Группировка по строкам (y_threshold=20)
        3. Для каждой строки:
           - Найти текст с 'Lv.' → извлечь уровень
           - Найти самый длинный текст без 'Lv.' → название здания
           - Увеличить счетчик для этого здания (индекс)
        4. Вычислить координаты кнопки "Перейти": (330, y_строки)

        Args:
            screenshot: numpy.ndarray (BGR формат)
            emulator_id: int (для debug, опционально)

        Returns:
            list: Список зданий
            [
                {
                    'name': 'Ферма Грунта',
                    'level': 1,
                    'index': 1,  # Первая из 4-х
                    'y_coord': 449,
                    'button_coord': (330, 449)
                },
                ...
            ]
        """
        logger.info("Парсинг панели навигации...")

        # 1. OCR распознавание
        elements = self.recognize_text(screenshot, min_confidence=0.5)

        # Debug режим - сохранить ВСЕГДА (даже если ничего не распознано)
        if self.debug_mode and emulator_id is not None:
            self._save_debug_image(screenshot, elements, emulator_id, "navigation")

        if not elements:
            logger.warning("OCR не распознал элементы на панели навигации")
            return []

        # 2. Группировка по строкам
        rows = self.group_by_rows(elements, y_threshold=20)

        # 3. Парсинг каждой строки
        buildings = []
        building_counters = {}  # {'Ферма Грунта': 0, 'Склад Грунта': 0}

        for row in rows:
            # Объединить весь текст строки
            full_text = ' '.join([elem['text'] for elem in row])

            # Извлечь уровень
            level = self.parse_level(full_text)

            # Извлечь название здания
            building_name = self.parse_building_name(full_text)

            # Проверка: нужно и название и уровень
            if not building_name or level is None:
                continue

            # Фильтр: название должно быть достаточно длинным
            if len(building_name) < 3:
                continue

            # Вычислить Y-координату строки (средняя по всем элементам)
            y_coord = int(sum([elem['y'] for elem in row]) / len(row))

            # Увеличить счетчик для этого здания
            if building_name not in building_counters:
                building_counters[building_name] = 0
            building_counters[building_name] += 1

            index = building_counters[building_name]

            # Координаты кнопки "Перейти"
            button_coord = (330, y_coord)

            buildings.append({
                'name': building_name,
                'level': level,
                'index': index,
                'y_coord': y_coord,
                'button_coord': button_coord
            })

        logger.success(f"Распознано {len(buildings)} зданий в панели навигации")

        return buildings

    def _save_debug_image(self, image, elements, emulator_id, operation):
        """
        Сохраняет debug скриншот с bbox и текстом

        Args:
            image: numpy.ndarray (оригинальное изображение)
            elements: список элементов из recognize_text()
            emulator_id: int (ID эмулятора)
            operation: str (тип операции: "navigation", "timer", "building_name")
        """
        try:
            # Создать папку для debug
            debug_folder = "data/screenshots/debug/ocr"
            os.makedirs(debug_folder, exist_ok=True)

            # Копировать изображение для рисования
            debug_img = image.copy()

            # Если нет элементов - сохранить просто скриншот с пометкой
            if not elements:
                # Добавить текст "NO TEXT DETECTED"
                cv2.putText(debug_img, "NO TEXT DETECTED BY OCR", (10, 30),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                logger.warning("OCR debug: текст не распознан на изображении")
            else:
                # Рисовать bbox и текст для каждого элемента
                for elem in elements:
                    bbox = elem['bbox']
                    text = elem['text']
                    confidence = elem['confidence']

                    # Цвет в зависимости от confidence
                    if confidence >= 0.9:
                        color = (0, 255, 0)  # Зеленый
                    elif confidence >= 0.7:
                        color = (0, 255, 255)  # Желтый
                    else:
                        color = (0, 0, 255)  # Красный

                    # Рисовать прямоугольник
                    points = np.array(bbox, dtype=np.int32)
                    cv2.polylines(debug_img, [points], True, color, 2)

                    # Текст над bbox
                    x = int(bbox[0][0])
                    y = int(bbox[0][1]) - 5
                    label = f"{text} ({confidence:.2f})"

                    # Фон для текста (для читаемости)
                    text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                    cv2.rectangle(debug_img,
                                (x, y - text_size[1] - 5),
                                (x + text_size[0], y),
                                (0, 0, 0),
                                -1)

                    # Сам текст
                    cv2.putText(debug_img, label, (x, y - 2),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            # Имя файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"emu{emulator_id}_{operation}_{timestamp}.png"
            filepath = os.path.join(debug_folder, filename)

            # Сохранить
            cv2.imwrite(filepath, debug_img)

            # Полный абсолютный путь для лога
            abs_path = os.path.abspath(filepath)
            logger.info(f"OCR debug скриншот сохранен: {abs_path}")
            print(f"   📁 {abs_path}")

        except Exception as e:
            logger.error(f"Ошибка сохранения OCR debug скриншота: {e}")


# ============================================
# Singleton
# ============================================

_ocr_instance = None

def get_ocr_engine():
    """
    Возвращает единственный экземпляр OCREngine (Singleton)

    При первом вызове создает экземпляр, при последующих возвращает существующий.
    Это экономит память (~500 МБ) и время на загрузку моделей PaddleOCR.

    Returns:
        OCREngine: глобальный экземпляр
    """
    global _ocr_instance

    if _ocr_instance is None:
        logger.info("Создание OCREngine (Singleton)...")
        _ocr_instance = OCREngine()
        logger.success("OCREngine готов к использованию")

    return _ocr_instance