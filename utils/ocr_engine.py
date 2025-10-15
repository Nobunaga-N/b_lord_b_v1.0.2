"""
OCR движок для распознавания текста в игре Beast Lord

Основан на PaddleOCR 3.x с поддержкой GPU
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
    OCR движок для распознавания текста (PaddleOCR 3.x)

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

        Note:
            Для качественного распознавания русского текста используется
            славянская модель 'eslav_PP-OCRv5_mobile_rec'.
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

        # Инициализация PaddleOCR 3.x с правильной славянской моделью
        try:
            device = 'gpu:0' if use_gpu else 'cpu'

            if lang == 'ru':
                logger.info("🔧 Загружаю славянскую модель с кириллицей...")

                # ПРАВИЛЬНАЯ ИНИЦИАЛИЗАЦИЯ для кириллицы в PaddleOCR 3.x
                self.ocr = PaddleOCR(
                    text_recognition_model_name="eslav_PP-OCRv5_mobile_rec",  # Славянская модель
                    use_doc_orientation_classify=False,  # Отключаем лишние модули для скорости
                    use_doc_unwarping=False,
                    use_textline_orientation=True,  # Включаем определение ориентации строк
                    device=device,
                )
                logger.success(f"✅ OCR инициализирован (модель: eslav, устройство: {device})")
            else:
                # Для других языков - стандартная модель
                self.ocr = PaddleOCR(
                    lang=lang,
                    device=device,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                )
                logger.success(f"✅ OCR инициализирован (язык: {lang}, устройство: {device})")

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации OCR: {e}")
            import traceback
            logger.error(traceback.format_exc())
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

        # Запуск OCR (PaddleOCR 3.x API)
        try:
            # В PaddleOCR 3.x метод predict возвращает список результатов
            result = self.ocr.predict(crop)

            logger.debug(f"🔍 OCR result type: {type(result)}")

            # result - это список OCRResult объектов (генератор)
            if hasattr(result, '__iter__') and not isinstance(result, (list, dict)):
                result = list(result)
                logger.debug(f"🔍 Converted generator to list, length: {len(result)}")

        except Exception as e:
            logger.error(f"❌ Ошибка OCR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

        # Парсинг результатов (PaddleOCR 3.x)
        elements = []

        try:
            if isinstance(result, list) and len(result) > 0:
                ocr_result = result[0]

                logger.debug(f"🔍 OCRResult type: {type(ocr_result)}")

                # OCRResult это dict-like объект
                boxes = None
                texts = None
                scores = None

                # Извлечение данных из результата
                if hasattr(ocr_result, 'keys'):
                    logger.debug(f"🔍 OCRResult keys: {list(ocr_result.keys())}")

                    # dt_polys - координаты bbox
                    if 'dt_polys' in ocr_result:
                        boxes = ocr_result['dt_polys']
                        logger.debug(f"🔍 Found dt_polys: type={type(boxes)}, len={len(boxes)}")

                    # rec_texts - распознанные тексты
                    if 'rec_texts' in ocr_result:
                        texts = ocr_result['rec_texts']
                        logger.debug(f"🔍 Found rec_texts: type={type(texts)}, len={len(texts)}")

                    # rec_scores - уверенность распознавания
                    if 'rec_scores' in ocr_result:
                        scores = ocr_result['rec_scores']
                        logger.debug(f"🔍 Found rec_scores: type={type(scores)}, len={len(scores)}")

                logger.debug(f"📦 Final data - boxes: {boxes is not None}, texts: {texts is not None}, scores: {scores is not None}")

                # Обработка данных
                if texts is not None and boxes is not None and scores is not None:
                    try:
                        logger.debug(f"📦 Найдено элементов: {len(texts)}")

                        for idx, (text, box, score) in enumerate(zip(texts, boxes, scores)):
                            # Фильтр по confidence
                            if score < min_confidence:
                                continue

                            # Преобразуем box в формат [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
                            if isinstance(box, np.ndarray):
                                # Находим минимальные и максимальные координаты
                                xs = box[:, 0]
                                ys = box[:, 1]
                                x_min, x_max = int(np.min(xs)), int(np.max(xs))
                                y_min, y_max = int(np.min(ys)), int(np.max(ys))
                            else:
                                # Если box уже в формате списка координат
                                x_min = min(p[0] for p in box)
                                x_max = max(p[0] for p in box)
                                y_min = min(p[1] for p in box)
                                y_max = max(p[1] for p in box)

                            # Координаты центра относительно оригинального изображения
                            center_x = x1 + (x_min + x_max) // 2
                            center_y = y1 + (y_min + y_max) // 2

                            elements.append({
                                'text': text,
                                'confidence': float(score),
                                'bbox': box.tolist() if isinstance(box, np.ndarray) else box,
                                'x': center_x,
                                'y': center_y,
                                'x_min': x1 + x_min,
                                'y_min': y1 + y_min,
                                'x_max': x1 + x_max,
                                'y_max': y1 + y_max,
                            })

                        logger.info(f"📊 OCR распознал {len(elements)} элементов")
                    except Exception as e:
                        logger.error(f"❌ Ошибка обработки результатов: {e}")
                        import traceback
                        logger.error(traceback.format_exc())

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга результатов: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Debug режим - сохранение скриншота с bbox
        if self.debug_mode and elements:
            self._save_debug_screenshot(crop, elements, region)

        return elements

    def parse_level(self, text: str) -> Optional[int]:
        """
        Парсинг уровня здания из текста (толерантен к ошибкам OCR)

        Args:
            text: Текст для парсинга

        Returns:
            Уровень здания или None

        Examples:
            >>> parse_level("Lv.10")
            10
            >>> parse_level("Ly.5")  # OCR ошибка: v → y
            5
            >>> parse_level("Lу.7")  # OCR ошибка: v → у (кириллица)
            7
            >>> parse_level("Level 3")
            3
        """
        # Толерантные паттерны (учитываем ошибки OCR)
        patterns = [
            r'[LlЛл][vVуУyYвВ]\.?\s*(\d+)',  # Lv, Ly, Lу, LУ и т.д.
            r'Level\s*(\d+)',                 # Level 10
            r'Ур\.?\s*(\d+)',                 # Ур. 10
            r'уровень\s*(\d+)',               # уровень 10
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def parse_timer(self, text: str) -> Optional[Dict[str, int]]:
        """
        Парсинг таймера из текста

        Args:
            text: Текст для парсинга

        Returns:
            Словарь с часами, минутами, секундами или None

        Examples:
            >>> parse_timer("10:41:48")
            {'hours': 10, 'minutes': 41, 'seconds': 48, 'total_seconds': 38508}
            >>> parse_timer("05:30")
            {'hours': 0, 'minutes': 5, 'seconds': 30, 'total_seconds': 330}
        """
        # Паттерны для таймеров
        patterns = [
            r'(\d{1,2}):(\d{2}):(\d{2})',  # HH:MM:SS
            r'(\d{1,2}):(\d{2})',          # MM:SS
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()

                if len(groups) == 3:
                    # HH:MM:SS
                    hours, minutes, seconds = map(int, groups)
                else:
                    # MM:SS
                    hours = 0
                    minutes, seconds = map(int, groups)

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
        Парсинг названия здания (убирает уровни и кнопки, но сохраняет римские цифры)

        Args:
            text: Текст для парсинга

        Returns:
            Очищенное название здания

        Examples:
            >>> parse_building_name("Жилище Лемуров I Lv.10 Перейти")
            "Жилище Лемуров I"
            >>> parse_building_name("Логово Хищников II Ly.5 Перейти")
            "Логово Хищников II"
        """
        # Убираем уровни (Lv.X, Ly.X и т.д.)
        text = re.sub(r'[LlЛл][vVуУyYвВ]\.?\s*\d+', '', text, flags=re.IGNORECASE)

        # Убираем "Перейти" и его варианты
        text = re.sub(r'[ПпPp][еeЕE][рpРP][еeЕE][йиĭІі][тtТT][иiІі]', '', text, flags=re.IGNORECASE)

        # НЕ убираем римские цифры - они часть названия здания!
        # Они отличают разные экземпляры одного типа (Жилище I, Жилище II, и т.д.)

        # Убираем лишние пробелы
        text = ' '.join(text.split())

        return text.strip()

    def group_by_rows(self, elements: List[Dict[str, Any]], y_threshold: int = 20) -> List[List[Dict[str, Any]]]:
        """
        Группировка элементов по строкам на основе Y-координат

        Args:
            elements: Список элементов с координатами
            y_threshold: Порог для группировки (пиксели)

        Returns:
            Список строк (каждая строка - список элементов)
        """
        if not elements:
            return []

        # Сортируем по Y
        sorted_elements = sorted(elements, key=lambda e: e['y'])

        rows = []
        current_row = [sorted_elements[0]]

        for elem in sorted_elements[1:]:
            # Если элемент близко по Y к текущей строке - добавляем
            if abs(elem['y'] - current_row[0]['y']) <= y_threshold:
                current_row.append(elem)
            else:
                # Новая строка
                # Сортируем элементы в строке по X
                current_row.sort(key=lambda e: e['x'])
                rows.append(current_row)
                current_row = [elem]

        # Добавляем последнюю строку
        if current_row:
            current_row.sort(key=lambda e: e['x'])
            rows.append(current_row)

        logger.info(f"📊 Сгруппировано в {len(rows)} строк")
        return rows

    def parse_navigation_panel(
        self,
        screenshot: np.ndarray,
        emulator_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Полный парсинг панели навигации (список зданий)

        Args:
            screenshot: Скриншот экрана
            emulator_id: ID эмулятора (для debug)

        Returns:
            Список зданий с координатами кнопки "Перейти"
        """
        # Распознаём весь текст на экране
        elements = self.recognize_text(screenshot, min_confidence=0.3)

        if not elements:
            logger.warning("⚠️ OCR не распознал ни одного элемента")
            return []

        # Группируем по строкам
        rows = self.group_by_rows(elements, y_threshold=20)

        buildings = []

        for row in rows:
            # Собираем текст строки
            row_text = ' '.join([elem['text'] for elem in row])
            logger.debug(f"📝 Строка: {row_text}")

            # Проверяем наличие уровня
            level = self.parse_level(row_text)
            if level is None:
                continue

            # Проверяем наличие кнопки "Перейти"
            has_button = any(
                re.search(r'[ПпPp][еeЕE][рpРP][еeЕE][йиĭІі][тtТT][иiІі]', elem['text'], re.IGNORECASE)
                for elem in row
            )

            if not has_button:
                continue

            # Парсим название здания
            building_name = self.parse_building_name(row_text)

            if not building_name:
                continue

            # Координаты кнопки "Перейти" (обычно последний элемент в строке)
            button_elem = row[-1]
            button_y = button_elem['y']

            buildings.append({
                'name': building_name,
                'level': level,
                'y': button_y,
                'raw_text': row_text
            })

            logger.info(f"✅ Здание: {building_name} Lv.{level} (Y: {button_y})")

        return buildings

    def _save_debug_screenshot(
        self,
        image: np.ndarray,
        elements: List[Dict],
        region: Optional[Tuple] = None
    ):
        """Сохранить debug скриншот с bbox"""
        try:
            debug_img = image.copy()

            for elem in elements:
                # Рисуем bbox
                box = elem['bbox']
                if isinstance(box, np.ndarray):
                    box = box.astype(int)
                else:
                    box = np.array(box, dtype=int)

                cv2.polylines(debug_img, [box], True, (0, 255, 0), 2)

                # Добавляем текст
                text = elem['text']
                confidence = elem['confidence']
                label = f"{text} ({confidence:.2f})"

                # Позиция текста
                if len(box) > 0:
                    x, y = int(box[0][0]), int(box[0][1]) - 5
                    cv2.putText(debug_img, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                              0.5, (0, 255, 0), 1, cv2.LINE_AA)

            # Сохраняем
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"emu1_navigation_{timestamp}.png"
            filepath = self.debug_dir / filename
            cv2.imwrite(str(filepath), debug_img)
            logger.info(f"🐛 Debug скриншот сохранён: {filepath}")

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения debug скриншота: {e}")