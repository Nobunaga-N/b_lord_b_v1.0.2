"""
OCR движок для распознавания текста в игре Beast Lord

Основан на PaddleX 3.2.x с поддержкой GPU
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
    from paddlex import create_pipeline
    import paddle
    PADDLE_AVAILABLE = True
except ImportError as e:
    logger.error(f"❌ Ошибка импорта PaddleX: {e}")
    PADDLE_AVAILABLE = False


class OCREngine:
    """
    OCR движок для распознавания текста (PaddleX 3.2.x)

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

            Если модель не загружена автоматически, установите вручную:
            pip install paddlex-eslav

            Или скачайте модель:
            https://paddleocr.bj.bcebos.com/dygraph_v2.0/multilingual/
        """
        if not PADDLE_AVAILABLE:
            raise RuntimeError("PaddleX не установлен! Установите: pip install paddlex paddlepaddle-gpu")

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

        # Инициализация PaddleX 3.2.x pipeline
        try:
            device = 'gpu:0' if use_gpu else 'cpu'

            if lang == 'ru':
                # КРИТИЧНО: Создаём словарь с кириллицей + латиницей + цифрами
                cyrillic_chars = (
                    "0123456789"
                    "abcdefghijklmnopqrstuvwxyz"
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
                    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
                    ".:,-()!?/\\ "
                )

                # Сохраняем словарь во временный файл
                dict_path = self.debug_dir / "cyrillic_dict.txt"
                with open(dict_path, 'w', encoding='utf-8') as f:
                    for char in cyrillic_chars:
                        f.write(char + '\n')

                logger.info(f"📝 Создан кириллический словарь: {dict_path}")

                # Пытаемся создать pipeline с кириллицей
                try:
                    # ВАРИАНТ 1: Явно указываем rec_char_dict_path
                    self.pipeline = create_pipeline(
                        pipeline="OCR",
                        device=device,
                        det_model="PP-OCRv5_server_det",
                        rec_model="PP-OCRv5_server_rec",
                        rec_char_dict_path=str(dict_path)  # Явно указываем словарь
                    )
                    logger.success(f"✅ OCR инициализирован с кириллическим словарём (устройство: {device})")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось загрузить с кастомным словарём: {e}")

                    # ВАРИАНТ 2: Fallback на многоязычную модель
                    try:
                        logger.info("🔄 Пробую многоязычную модель...")
                        self.pipeline = create_pipeline(
                            pipeline="OCR",
                            device=device,
                            language="cyrillic"  # Многоязычный режим
                        )
                        logger.success(f"✅ OCR инициализирован (многоязычная модель, устройство: {device})")
                    except Exception as e2:
                        logger.error(f"❌ Многоязычная модель тоже не работает: {e2}")

                        # ВАРИАНТ 3: Последняя попытка - дефолтная модель
                        logger.warning("⚠️ Использую дефолтную модель (без гарантий кириллицы)")
                        self.pipeline = create_pipeline(
                            pipeline="OCR",
                            device=device
                        )
            else:
                # Для других языков - стандартная модель
                self.pipeline = create_pipeline(
                    pipeline="OCR",
                    device=device
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

        # Запуск OCR (PaddleX 3.2.x API)
        try:
            # PaddleX 3.x принимает numpy array или путь к файлу
            result = self.pipeline.predict(crop)

            logger.debug(f"🔍 OCR result type: {type(result)}")

            # В PaddleX 3.2.x результат может быть генератором
            # Преобразуем в список
            if hasattr(result, '__iter__') and not isinstance(result, (list, dict)):
                result = list(result)
                logger.debug(f"🔍 Converted generator to list, length: {len(result)}")

        except Exception as e:
            logger.error(f"❌ Ошибка OCR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

        # Парсинг результатов (PaddleX 3.2.x)
        elements = []

        try:
            # В PaddleX 3.x результат это список OCRResult объектов
            if isinstance(result, list) and len(result) > 0:
                ocr_result = result[0]

                # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для отладки
                logger.debug(f"🔍 OCRResult type: {type(ocr_result)}")

                # OCRResult это dict-like объект, работаем как со словарём
                if hasattr(ocr_result, 'keys'):
                    logger.debug(f"🔍 OCRResult keys: {list(ocr_result.keys())}")

                # Инициализация переменных
                boxes = None
                texts = None
                scores = None

                # Попробуем разные ключи для извлечения данных
                # PaddleX 3.x использует dict-like структуру
                if hasattr(ocr_result, 'keys'):
                    # Поиск координат bbox
                    for box_key in ['dt_polys', 'rec_polys', 'boxes', 'bbox', 'dt_boxes', 'bboxes']:
                        if box_key in ocr_result:
                            boxes = ocr_result[box_key]
                            logger.debug(f"🔍 Found {box_key}: type={type(boxes)}, len={len(boxes) if hasattr(boxes, '__len__') else 'N/A'}")
                            break

                    # Поиск текстов
                    for text_key in ['rec_texts', 'rec_text', 'texts', 'text', 'ocr_text']:
                        if text_key in ocr_result:
                            texts = ocr_result[text_key]
                            logger.debug(f"🔍 Found {text_key}: type={type(texts)}, len={len(texts) if hasattr(texts, '__len__') else 'N/A'}")
                            break

                    # Поиск scores
                    for score_key in ['rec_scores', 'rec_score', 'scores', 'score', 'confidence']:
                        if score_key in ocr_result:
                            scores = ocr_result[score_key]
                            logger.debug(f"🔍 Found {score_key}: type={type(scores)}, len={len(scores) if hasattr(scores, '__len__') else 'N/A'}")
                            break

                logger.debug(f"📦 Final data - boxes: {boxes is not None}, texts: {texts is not None}, scores: {scores is not None}")

                # Попробуем обработать данные
                if texts is not None and boxes is not None and scores is not None:
                    logger.debug(f"📦 Найдено элементов: {len(texts)}")

                    for bbox, text, score in zip(boxes, texts, scores):
                        if score < min_confidence:
                            continue

                        # bbox может быть numpy array - преобразуем в список
                        if hasattr(bbox, 'tolist'):
                            bbox = bbox.tolist()

                        # Вычислить центр bbox
                        if isinstance(bbox, list) and len(bbox) >= 4:
                            # Формат: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                            # Или: [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
                            try:
                                # Извлечь все X и Y координаты
                                xs = [p[0] for p in bbox]
                                ys = [p[1] for p in bbox]
                                center_x = int(sum(xs) / len(xs)) + x1
                                center_y = int(sum(ys) / len(ys)) + y1

                                elements.append({
                                    'text': str(text),
                                    'confidence': float(score),
                                    'x': center_x,
                                    'y': center_y,
                                    'bbox': [[int(p[0]) + x1, int(p[1]) + y1] for p in bbox]
                                })
                            except Exception as e:
                                logger.debug(f"⚠️ Ошибка обработки bbox: {e}, bbox={bbox}")
                                continue

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга результатов OCR: {e}")
            import traceback
            logger.error(traceback.format_exc())

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

        Returns:
            {'hours': 10, 'minutes': 41, 'seconds': 48, 'total_seconds': 38508}
            или None
        """
        # Формат: HH:MM:SS
        match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})', text)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = int(match.group(3))
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return {
                'hours': hours,
                'minutes': minutes,
                'seconds': seconds,
                'total_seconds': total_seconds
            }

        # Формат: MM:SS
        match = re.search(r'(\d{1,2}):(\d{2})', text)
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            total_seconds = minutes * 60 + seconds
            return {
                'hours': 0,
                'minutes': minutes,
                'seconds': seconds,
                'total_seconds': total_seconds
            }

        return None

    def parse_building_name(self, text: str) -> str:
        """
        Парсинг названия здания

        Удаляет:
        - Уровни (Lv.X, Ly.X)
        - Кнопки (Перейти)
        - Римские цифры (I, II, III, IV)

        Example:
            "Жилище Лемуров I Lv.10 Перейти" -> "Жилище Лемуров"
        """
        # Удалить уровни
        text = re.sub(r'[LlЛл][vVуУyYвВ]\.?\s*\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Level\s*\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Ур\.?\s*\d+', '', text, flags=re.IGNORECASE)

        # Удалить кнопку "Перейти" и её искажения
        text = re.sub(r'Перейти|ерећти|Переити|ereyti', '', text, flags=re.IGNORECASE)

        # Удалить римские цифры в конце (I, II, III, IV, V)
        text = re.sub(r'\s+[IVX]+$', '', text)

        # Убрать лишние пробелы
        text = ' '.join(text.split())

        return text.strip()

    def group_by_rows(self, elements: List[Dict], y_threshold: int = 20) -> List[List[Dict]]:
        """
        Группировка элементов по строкам на основе Y-координат

        Args:
            elements: Список элементов с координатами
            y_threshold: Порог по Y для группировки (пикселей)

        Returns:
            Список строк (каждая строка - список элементов)
        """
        if not elements:
            return []

        # Сортировка по Y
        sorted_elements = sorted(elements, key=lambda e: e['y'])

        rows = []
        current_row = [sorted_elements[0]]
        current_y = sorted_elements[0]['y']

        for elem in sorted_elements[1:]:
            if abs(elem['y'] - current_y) <= y_threshold:
                # Элемент на той же строке
                current_row.append(elem)
            else:
                # Новая строка
                # Сортировка текущей строки по X
                current_row.sort(key=lambda e: e['x'])
                rows.append(current_row)

                current_row = [elem]
                current_y = elem['y']

        # Добавить последнюю строку
        if current_row:
            current_row.sort(key=lambda e: e['x'])
            rows.append(current_row)

        return rows

    def parse_navigation_panel(
        self,
        screenshot: np.ndarray,
        emulator_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Парсинг панели навигации

        Returns:
            Список зданий с информацией:
            [
                {
                    'name': 'Логово Травоядных',
                    'level': 2,
                    'y_coord': 435,
                    'button_coord': (330, 435)
                },
                ...
            ]
        """
        # Распознать весь текст
        elements = self.recognize_text(screenshot, min_confidence=0.3)
        logger.debug(f"📊 OCR распознал {len(elements)} элементов")

        if not elements:
            logger.warning("⚠️ OCR не распознал ни одного элемента")
            return []

        # Сохранить debug скриншот если включен режим
        if self.debug_mode:
            self._save_debug_screenshot(screenshot, elements, emulator_id)

        # Группировка по строкам
        rows = self.group_by_rows(elements, y_threshold=20)
        logger.debug(f"📊 Сгруппировано в {len(rows)} строк")

        # Парсинг зданий
        buildings = []

        for row in rows:
            # Объединить текст строки
            row_text = ' '.join([e['text'] for e in row])
            logger.debug(f"📝 Строка: {row_text}")

            # Попробовать извлечь уровень
            level = self.parse_level(row_text)

            # Если нет уровня - пропустить
            if level is None:
                continue

            # Извлечь название здания
            name = self.parse_building_name(row_text)

            # Если название пустое - пропустить
            if not name:
                continue

            # Y-координата = средняя Y элементов строки
            y_coord = int(sum([e['y'] for e in row]) / len(row))

            # Координата кнопки "Перейти" (справа от текста)
            button_x = 330  # Фиксированная X координата кнопки
            button_y = y_coord

            buildings.append({
                'name': name,
                'level': level,
                'y_coord': y_coord,
                'button_coord': (button_x, button_y)
            })

            logger.debug(f"✅ Здание: {name} Lv.{level} (Y: {y_coord})")

        return buildings

    def _save_debug_screenshot(
        self,
        screenshot: np.ndarray,
        elements: List[Dict],
        emulator_id: Optional[int] = None
    ):
        """Сохранить debug скриншот с bbox"""
        img = screenshot.copy()

        # Нарисовать bbox для каждого элемента
        for elem in elements:
            bbox = elem['bbox']
            text = elem['text']
            conf = elem['confidence']

            # Преобразовать bbox в формат для cv2.polylines
            pts = np.array(bbox, dtype=np.int32).reshape((-1, 1, 2))

            # Цвет: зелёный если conf > 0.5, иначе жёлтый
            color = (0, 255, 0) if conf > 0.5 else (0, 255, 255)

            # Нарисовать bbox
            cv2.polylines(img, [pts], True, color, 2)

            # Нарисовать текст
            cv2.putText(
                img,
                f"{text} ({conf:.2f})",
                (int(bbox[0][0]), int(bbox[0][1]) - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1
            )

        # Сохранить
        timestamp = datetime.now().strftime("%H%M%S")
        emu_prefix = f"emu{emulator_id}_" if emulator_id else ""
        filename = self.debug_dir / f"{emu_prefix}navigation_{timestamp}.png"

        cv2.imwrite(str(filename), img)
        logger.debug(f"🐛 Debug скриншот сохранён: {filename}")