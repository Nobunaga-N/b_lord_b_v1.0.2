"""
OCR движок для распознавания текста в игре Beast Lord

Основан на PaddleOCR 3.2.0 с поддержкой GPU
Адаптирован под русский язык и специфику игры
"""

import re
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import cv2
from loguru import logger

try:
    from paddleocr import PaddleOCR
    import paddle
    PADDLE_AVAILABLE = True
except ImportError as e:
    logger.error(f"❌ Ошибка импорта PaddleOCR: {e}")
    PADDLE_AVAILABLE = False


class OCREngine:
    """
    OCR движок для распознавания текста

    Features:
    - Автоматическое определение GPU/CPU
    - Русский язык (кириллица + латиница)
    - Парсинг уровней зданий (Lv.X)
    - Парсинг таймеров (HH:MM:SS)
    - Построчная группировка элементов
    - Debug режим с сохранением bbox
    """

    def __init__(self, lang: str = 'ru', force_cpu: bool = False):
        """
        Инициализация OCR движка

        Args:
            lang: Язык распознавания ('ru', 'en', 'ch')
            force_cpu: Принудительно использовать CPU
        """
        if not PADDLE_AVAILABLE:
            raise RuntimeError("PaddleOCR не установлен! Установите: pip install paddleocr paddlepaddle-gpu")

        self.lang = lang
        self.debug_mode = False
        self.debug_dir = Path("data/screenshots/debug/ocr")
        self.debug_dir.mkdir(parents=True, exist_ok=True)

        # Проверка GPU
        use_gpu = False
        if not force_cpu:
            try:
                use_gpu = paddle.device.is_compiled_with_cuda()
                if use_gpu:
                    gpu_count = paddle.device.cuda.device_count()
                    logger.info(f"🎮 GPU обнаружен! Доступно устройств: {gpu_count}")
                else:
                    logger.warning("⚠️ GPU не обнаружен, используется CPU")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка проверки GPU: {e}, используется CPU")
                use_gpu = False
        else:
            logger.info("🔧 Принудительно используется CPU")

        # Инициализация PaddleOCR 3.2.0
        # В версии 3.x параметры изменились: use_gpu -> device
        try:
            device = 'gpu' if use_gpu else 'cpu'
            self.ocr = PaddleOCR(
                lang=lang,
                device=device  # 'gpu' или 'cpu'
            )
            logger.success(f"✅ OCR инициализирован (язык: {lang}, устройство: {device})")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации OCR: {e}")
            raise

    def set_debug_mode(self, enabled: bool):
        """Включить/выключить debug режим (сохранение скриншотов с bbox)"""
        self.debug_mode = enabled
        logger.info(f"🐛 Debug режим: {'ВКЛ' if enabled else 'ВЫКЛ'}")

    def recognize_text(
        self,
        image: np.ndarray,
        region: Optional[Tuple[int, int, int, int]] = None,
        min_confidence: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Универсальное распознавание текста

        Args:
            image: Изображение (BGR формат)
            region: Регион для распознавания (x1, y1, x2, y2)
            min_confidence: Минимальная уверенность (0.3 для захвата цифр)

        Returns:
            Список элементов с текстом, bbox и координатами
        """
        # Извлечь регион если указан
        if region:
            x1, y1, x2, y2 = region
            crop = image[y1:y2, x1:x2]
        else:
            crop = image
            x1, y1 = 0, 0

        # Запуск OCR (PaddleX 3.2.0 API)
        try:
            result = self.ocr.predict(crop)

            # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для отладки
            logger.debug(f"🔍 OCR result type: {type(result)}")

            if isinstance(result, list) and len(result) > 0:
                logger.debug(f"🔍 OCR result list length: {len(result)}")
                first_elem = result[0]
                logger.debug(f"🔍 First element type: {type(first_elem)}")

                # Если это объект OCRResult, показать его атрибуты
                if hasattr(first_elem, '__dict__'):
                    logger.debug(f"🔍 OCRResult attributes: {list(first_elem.__dict__.keys())}")
                    # Попробовать вывести содержимое
                    for attr in ['boxes', 'dt_polys', 'rec_text', 'texts', 'rec_score', 'scores']:
                        if hasattr(first_elem, attr):
                            value = getattr(first_elem, attr)
                            logger.debug(f"🔍 OCRResult.{attr}: {type(value)} = {str(value)[:200]}")

                # Попробовать вызвать метод json() если есть
                if hasattr(first_elem, 'json'):
                    try:
                        json_data = first_elem.json()
                        logger.debug(f"🔍 OCRResult.json(): {str(json_data)[:300]}")
                    except:
                        pass

                # Попробовать преобразовать в dict
                if hasattr(first_elem, 'to_dict'):
                    try:
                        dict_data = first_elem.to_dict()
                        logger.debug(f"🔍 OCRResult.to_dict(): {str(dict_data)[:300]}")
                    except:
                        pass

            elif isinstance(result, dict):
                logger.debug(f"🔍 OCR result keys: {list(result.keys())}")
                for key, value in result.items():
                    value_str = str(value)[:200]
                    logger.debug(f"🔍 result['{key}']: {value_str}...")
            else:
                logger.debug(f"🔍 OCR result: {str(result)[:200]}")

        except Exception as e:
            logger.error(f"❌ Ошибка OCR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

        # Парсинг результатов (PaddleX 3.2.0)
        elements = []

        # Вариант 1: Результат - список с объектом OCRResult
        if isinstance(result, list) and len(result) > 0:
            ocr_result = result[0]

            # Попробовать извлечь данные из OCRResult объекта
            boxes = None
            texts = None
            scores = None

            # Попробовать разные варианты атрибутов
            for box_attr in ['boxes', 'dt_polys', 'bbox', 'bboxes']:
                if hasattr(ocr_result, box_attr):
                    boxes = getattr(ocr_result, box_attr)
                    break

            for text_attr in ['texts', 'rec_text', 'text', 'rec_texts']:
                if hasattr(ocr_result, text_attr):
                    texts = getattr(ocr_result, text_attr)
                    break

            for score_attr in ['scores', 'rec_score', 'score', 'confidences']:
                if hasattr(ocr_result, score_attr):
                    scores = getattr(ocr_result, score_attr)
                    break

            # Если нашли данные, обработать
            if boxes is not None and texts is not None:
                logger.debug(f"✅ Извлечено: boxes={len(boxes)}, texts={len(texts)}")

                # Если scores нет, создать массив единиц
                if scores is None:
                    scores = [1.0] * len(texts)

                # Обработать каждый элемент
                for i, (bbox, text) in enumerate(zip(boxes, texts)):
                    confidence = scores[i] if i < len(scores) else 1.0

                    # Фильтр по confidence
                    if confidence < min_confidence:
                        continue

                    # bbox может быть в разных форматах
                    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                        # Формат: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                        if isinstance(bbox[0], (list, tuple)) and len(bbox[0]) >= 2:
                            x_coords = [p[0] for p in bbox]
                            y_coords = [p[1] for p in bbox]
                            center_x = int(sum(x_coords) / len(x_coords)) + x1
                            center_y = int(sum(y_coords) / len(y_coords)) + y1

                            elements.append({
                                'text': str(text),
                                'confidence': float(confidence),
                                'x': center_x,
                                'y': center_y,
                                'bbox': [[p[0] + x1, p[1] + y1] for p in bbox]
                            })
                        # Формат: [x1, y1, x2, y2]
                        elif all(isinstance(x, (int, float)) for x in bbox):
                            center_x = int((bbox[0] + bbox[2]) / 2) + x1
                            center_y = int((bbox[1] + bbox[3]) / 2) + y1

                            elements.append({
                                'text': str(text),
                                'confidence': float(confidence),
                                'x': center_x,
                                'y': center_y,
                                'bbox': [
                                    [bbox[0] + x1, bbox[1] + y1],
                                    [bbox[2] + x1, bbox[1] + y1],
                                    [bbox[2] + x1, bbox[3] + y1],
                                    [bbox[0] + x1, bbox[3] + y1]
                                ]
                            })

        # Вариант 2: Результат - dict (старый формат)
        elif isinstance(result, dict):
            # ... (оставить старый код для совместимости)
            pass

        logger.debug(f"📊 OCR распознал {len(elements)} элементов")
        return elements

    def parse_level(self, text: str) -> Optional[int]:
        """
        Парсинг уровня здания (толерантен к ошибкам OCR)

        Распознает:
        - Lv.10, Ly.5, Lу.7 (OCR иногда путает v/y/у)
        - Level 10
        - Ур.10

        Returns:
            Уровень здания или None
        """
        patterns = [
            r'[LlЛл][vVуУyYвВ]\.?\s*(\d+)',  # Lv, Ly, Lу, LУ
            r'Level\s*(\d+)',
            r'Ур\.?\s*(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def parse_timer(self, text: str) -> Optional[Dict[str, int]]:
        """
        Парсинг таймера (HH:MM:SS или MM:SS)

        Args:
            text: Строка с таймером

        Returns:
            {'hours': int, 'minutes': int, 'seconds': int, 'total_seconds': int}
        """
        # Формат: HH:MM:SS или MM:SS
        pattern = r'(\d+):(\d+):(\d+)'
        match = re.search(pattern, text)

        if match:
            parts = [int(x) for x in match.groups()]

            if len(parts) == 3:
                if parts[0] < 24:  # HH:MM:SS
                    hours, minutes, seconds = parts
                else:  # MM:SS (первое число - минуты)
                    hours = 0
                    minutes, seconds = parts[0], parts[1]
            else:
                return None

            total_seconds = hours * 3600 + minutes * 60 + seconds

            return {
                'hours': hours,
                'minutes': minutes,
                'seconds': seconds,
                'total_seconds': total_seconds
            }

        return None

    def parse_building_name(self, text: str) -> str:
        """
        Парсинг названия здания (очистка от мусора)

        Удаляет:
        - Уровни (Lv.X, Ly.X)
        - Кнопки (Перейти)
        - Римские цифры (I, II, III, IV)

        Examples:
            "Жилище Лемуров I Lv.10" -> "Жилище Лемуров"
            "Ферма Песка Перейти" -> "Ферма Песка"
        """
        # Удалить уровни
        text = re.sub(r'[LlЛл][vVуУyYвВ]\.?\s*\d+', '', text, flags=re.IGNORECASE)

        # Удалить "Перейти"
        text = re.sub(r'Перейти|ерећти|Переити', '', text, flags=re.IGNORECASE)

        # Удалить римские цифры в конце
        text = re.sub(r'\s+[IVX]+\s*$', '', text)

        # Убрать лишние пробелы
        text = ' '.join(text.split())

        return text.strip()

    def group_by_rows(
        self,
        elements: List[Dict[str, Any]],
        y_threshold: int = 20
    ) -> List[List[Dict[str, Any]]]:
        """
        Группировка элементов по строкам на основе Y-координат

        Args:
            elements: Список элементов с координатами
            y_threshold: Порог для объединения в одну строку (px)

        Returns:
            Список строк (каждая строка = список элементов)
        """
        if not elements:
            return []

        # Сортировка по Y
        sorted_elements = sorted(elements, key=lambda x: x['y'])

        rows = []
        current_row = [sorted_elements[0]]

        for elem in sorted_elements[1:]:
            # Если элемент близко к текущей строке
            if abs(elem['y'] - current_row[0]['y']) <= y_threshold:
                current_row.append(elem)
            else:
                # Сортировка строки по X
                current_row.sort(key=lambda x: x['x'])
                rows.append(current_row)
                current_row = [elem]

        # Добавить последнюю строку
        if current_row:
            current_row.sort(key=lambda x: x['x'])
            rows.append(current_row)

        return rows

    def parse_navigation_panel(
        self,
        screenshot: np.ndarray,
        emulator_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Полный парсинг панели навигации

        Возвращает список зданий с уровнями и координатами кнопки "Перейти"

        Args:
            screenshot: Скриншот панели навигации
            emulator_id: ID эмулятора (для debug)

        Returns:
            [
                {
                    'name': 'Жилище Детенышей',
                    'level': 7,
                    'y_coord': 582,
                    'button_coord': (330, 582)
                },
                ...
            ]
        """
        # Распознать весь текст
        elements = self.recognize_text(screenshot, min_confidence=0.3)

        logger.info(f"📊 OCR распознал {len(elements)} элементов")

        # Debug режим: сохранить RAW скриншот даже если нет элементов
        if self.debug_mode and emulator_id is not None:
            self._save_debug_screenshot(screenshot, elements, [], emulator_id)

        if not elements:
            logger.warning("⚠️ OCR не распознал ни одного элемента")
            return []

        # Группировка по строкам
        rows = self.group_by_rows(elements, y_threshold=20)

        # Парсинг каждой строки
        buildings = []
        for row in rows:
            building_name = None
            building_level = None
            row_y = row[0]['y']  # Y-координата строки

            for elem in row:
                # Попытка распознать уровень
                level = self.parse_level(elem['text'])
                if level:
                    building_level = level
                # Попытка распознать название
                elif len(elem['text']) > 3 and 'Перейти' not in elem['text']:
                    building_name = self.parse_building_name(elem['text'])

            # Если нашли и название и уровень
            if building_name and building_level:
                buildings.append({
                    'name': building_name,
                    'level': building_level,
                    'y_coord': row_y,
                    'button_coord': (330, row_y)  # Кнопка "Перейти" всегда на X=330
                })

        # Debug режим: обновить скриншот с найденными зданиями
        if self.debug_mode and emulator_id is not None and buildings:
            self._save_debug_screenshot(screenshot, elements, buildings, emulator_id)

        logger.info(f"🏢 Распознано зданий: {len(buildings)}")
        return buildings

    def _save_debug_screenshot(
        self,
        screenshot: np.ndarray,
        elements: List[Dict[str, Any]],
        buildings: List[Dict[str, Any]],
        emulator_id: int
    ):
        """Сохранить debug скриншот с bbox и распознанным текстом"""
        try:
            debug_img = screenshot.copy()

            # Нарисовать bbox для всех элементов
            for elem in elements:
                bbox = elem['bbox']
                pts = np.array(bbox, dtype=np.int32)
                cv2.polylines(debug_img, [pts], True, (0, 255, 0), 2)

                # Подпись с текстом
                text = f"{elem['text']} ({elem['confidence']:.2f})"
                cv2.putText(
                    debug_img, text,
                    (int(bbox[0][0]), int(bbox[0][1]) - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1
                )

            # Нарисовать найденные здания
            for i, building in enumerate(buildings):
                y = building['y_coord']
                # Линия через всю строку
                cv2.line(debug_img, (0, y), (540, y), (255, 0, 0), 2)
                # Точка кнопки "Перейти"
                cv2.circle(debug_img, building['button_coord'], 5, (0, 0, 255), -1)

            # Добавить информацию в заголовок
            info_text = f"Elements: {len(elements)}, Buildings: {len(buildings)}"
            cv2.putText(
                debug_img, info_text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
            )

            # Сохранить
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"emu{emulator_id}_navigation_{timestamp}.png"
            filepath = self.debug_dir / filename
            cv2.imwrite(str(filepath), debug_img)
            logger.success(f"🐛 Debug скриншот сохранён: {filepath}")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения debug скриншота: {e}")
            import traceback
            logger.error(traceback.format_exc())