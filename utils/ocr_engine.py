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
    - Коррекция римских цифр через анализ изображения
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

                self.ocr = PaddleOCR(
                    text_recognition_model_name="eslav_PP-OCRv5_mobile_rec",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                    device=device,
                )
                logger.success(f"✅ OCR инициализирован (модель: eslav, устройство: {device})")
            else:
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

    def normalize_cyrillic_text(self, text: str) -> str:
        """
        Нормализация текста: заменяет визуально похожие латинские символы на кириллицу

        Применяется к ВСЕМУ распознанному тексту, кроме аббревиатур уровней (Lv.).
        """
        # Сохраняем аббревиатуры уровней "Lv."
        level_match = re.search(r'[LlЛл][vVуУyYвВ]\.?\s*\d+', text, flags=re.IGNORECASE)
        level_text = level_match.group() if level_match else None

        replacements = {
            'y': 'у', 'p': 'р', 'c': 'с', 'o': 'о', 'a': 'а',
            'e': 'е', 'x': 'х', 'k': 'к',
            'B': 'В', 'H': 'Н', 'P': 'Р', 'C': 'С', 'T': 'Т',
            'Y': 'У', 'O': 'О', 'A': 'А', 'E': 'Е', 'X': 'Х', 'K': 'К',
        }

        normalized = text
        for lat, cyr in replacements.items():
            normalized = normalized.replace(lat, cyr)

        if level_text:
            normalized_level = re.search(r'[LlЛл][vVуУyYвВ]\.?\s*\d+', normalized, flags=re.IGNORECASE)
            if normalized_level:
                normalized = normalized.replace(normalized_level.group(), level_text)

        return normalized

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
        if region:
            x1, y1, x2, y2 = region
            crop = image[y1:y2, x1:x2]
        else:
            crop = image
            x1, y1 = 0, 0

        try:
            result = self.ocr.predict(crop)
            logger.debug(f"🔍 OCR result type: {type(result)}")

            if hasattr(result, '__iter__') and not isinstance(result, (list, dict)):
                result = list(result)
                logger.debug(f"🔍 Converted generator to list, length: {len(result)}")

        except Exception as e:
            logger.error(f"❌ Ошибка OCR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

        elements = []

        try:
            if isinstance(result, list) and len(result) > 0:
                ocr_result = result[0]
                logger.debug(f"🔍 OCRResult type: {type(ocr_result)}")

                boxes = None
                texts = None
                scores = None

                if hasattr(ocr_result, 'keys'):
                    logger.debug(f"🔍 OCRResult keys: {list(ocr_result.keys())}")

                    if 'dt_polys' in ocr_result:
                        boxes = ocr_result['dt_polys']
                        logger.debug(f"🔍 Found dt_polys: type={type(boxes)}, len={len(boxes)}")
                    if 'rec_texts' in ocr_result:
                        texts = ocr_result['rec_texts']
                        logger.debug(f"🔍 Found rec_texts: type={type(texts)}, len={len(texts)}")
                    if 'rec_scores' in ocr_result:
                        scores = ocr_result['rec_scores']
                        logger.debug(f"🔍 Found rec_scores: type={type(scores)}, len={len(scores)}")

                logger.debug(f"📦 Final data - boxes: {boxes is not None}, texts: {texts is not None}, scores: {scores is not None}")

                if texts is not None and boxes is not None and scores is not None:
                    try:
                        logger.debug(f"📦 Найдено элементов: {len(texts)}")

                        for idx, (text, box, score) in enumerate(zip(texts, boxes, scores)):
                            if score < min_confidence:
                                continue

                            if isinstance(box, np.ndarray):
                                xs = box[:, 0]
                                ys = box[:, 1]
                                x_min, x_max = int(np.min(xs)), int(np.max(xs))
                                y_min, y_max = int(np.min(ys)), int(np.max(ys))
                            else:
                                x_min = min(p[0] for p in box)
                                x_max = max(p[0] for p in box)
                                y_min = min(p[1] for p in box)
                                y_max = max(p[1] for p in box)

                            center_x = x1 + (x_min + x_max) // 2
                            center_y = y1 + (y_min + y_max) // 2

                            elements.append({
                                'text': self.normalize_cyrillic_text(text),
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

        if self.debug_mode and elements:
            self._save_debug_screenshot(crop, elements, region)

        return elements

    # ==================== КОРРЕКЦИЯ РИМСКИХ ЦИФР ====================

    def _count_vertical_strokes(self, screenshot: np.ndarray,
                                x1: int, y1: int, x2: int, y2: int) -> int:
        """
        Подсчёт вертикальных штрихов в области изображения.

        Используется для определения римской цифры (I=1, II=2, III=3).
        PaddleOCR корректно ДЕТЕКТИРУЕТ bbox вокруг "III", но РАСПОЗНАЁТ
        как "I" из-за повторяющихся тонких штрихов.

        Алгоритм:
        1. Кроп области из скриншота
        2. Перевод в grayscale + бинаризация (Otsu)
        3. Вертикальная проекция (сумма по столбцам)
        4. Подсчёт пиков (переходов фон→штрих)

        Args:
            screenshot: Полный скриншот (BGR)
            x1, y1, x2, y2: Координаты области с римской цифрой

        Returns:
            Количество вертикальных штрихов (0 если не удалось определить)
        """
        h, w = screenshot.shape[:2]

        # Защита от выхода за границы + небольшой padding
        pad = 2
        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(w, x2 + pad)
        y2 = min(h, y2 + pad)

        crop = screenshot[y1:y2, x1:x2]
        if crop.size == 0 or (x2 - x1) < 3 or (y2 - y1) < 3:
            return 0

        # Grayscale
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop

        # Бинаризация (Otsu автоматически выбирает порог)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # В игре текст СВЕТЛЫЙ на ТЁМНОМ фоне
        # Если среднее яркое — значит текст уже белый, ОК
        # Если среднее тёмное — инвертируем чтобы штрихи стали белыми
        if np.mean(binary) < 127:
            binary = cv2.bitwise_not(binary)

        # Вертикальная проекция: сумма пикселей по каждому столбцу
        projection = np.sum(binary, axis=0).astype(float)

        if projection.max() == 0:
            return 0

        # Порог для определения "это штрих" — 30% от максимума проекции
        threshold = projection.max() * 0.3

        # Подсчёт штрихов (переходов ниже_порога → выше_порога)
        strokes = 0
        in_stroke = False
        stroke_width = 0
        min_stroke_width = 2  # Минимум 2 пикселя ширины для штриха

        for val in projection:
            if val > threshold:
                if not in_stroke:
                    in_stroke = True
                    stroke_width = 1
                else:
                    stroke_width += 1
            else:
                if in_stroke and stroke_width >= min_stroke_width:
                    strokes += 1
                in_stroke = False
                stroke_width = 0

        # Последний штрих (если закончился на краю)
        if in_stroke and stroke_width >= min_stroke_width:
            strokes += 1

        return strokes

    def _correct_roman_numeral(self, screenshot: np.ndarray,
                               row: List[Dict[str, Any]]) -> Optional[str]:
        """
        Определить реальную римскую цифру в строке здания через анализ изображения.

        СТРАТЕГИЯ 1: Ищет отдельный OCR-элемент с римской цифрой (I/l/1/|),
                     кропает его bbox и считает вертикальные штрихи.

        СТРАТЕГИЯ 2 (НОВАЯ): Если отдельного элемента нет (OCR склеил
                     "Лемуров III" → "Лемуров I"), сканирует область
                     СЛЕВА от элемента "Lv." — именно там на экране
                     находится римская цифра.

        Args:
            screenshot: Полный скриншот (BGR)
            row: Список OCR-элементов одной строки

        Returns:
            Скорректированная римская цифра ("I", "II", "III", "IV") или None
        """
        # ─── Находим элемент "Lv." для привязки координат ───
        lv_elem = None
        for elem in row:
            if re.search(r'[LlЛл][vVуУyYвВ]', elem['text']):
                lv_elem = elem
                break

        if lv_elem is None:
            return None

        lv_x_min = lv_elem['x_min']

        # ═══════════════════════════════════════════════════════
        # СТРАТЕГИЯ 1: Отдельный OCR-элемент с римской цифрой
        # ═══════════════════════════════════════════════════════
        roman_elem = None
        for elem in row:
            text = elem['text'].strip()

            # Пропускаем элементы после "Lv." — это не римская цифра
            if elem['x_min'] >= lv_x_min:
                continue

            # Пропускаем элементы с кириллицей (это слова, не цифры)
            if re.search(r'[а-яА-ЯёЁ]', text):
                continue

            # Проверяем: элемент похож на римскую цифру?
            if re.match(r'^[IiІі1lL|]{1,4}$', text):
                roman_elem = elem
                break

        if roman_elem:
            # Считаем штрихи в bbox отдельного элемента
            strokes = self._count_vertical_strokes(
                screenshot,
                roman_elem['x_min'], roman_elem['y_min'],
                roman_elem['x_max'], roman_elem['y_max']
            )

            if strokes > 0:
                return self._strokes_to_roman(strokes, roman_elem['text'])

        # ═══════════════════════════════════════════════════════
        # СТРАТЕГИЯ 2: Сканируем область СЛЕВА от "Lv."
        # OCR склеил римскую цифру с названием здания
        # ═══════════════════════════════════════════════════════

        # Проверяем: есть ли в строке хотя бы один элемент с кириллицей
        # (т.е. это строка здания, а не заголовок/кнопка)
        has_cyrillic_name = False
        for elem in row:
            if elem['x_min'] >= lv_x_min:
                continue
            if re.search(r'[а-яА-ЯёЁ]', elem['text']):
                has_cyrillic_name = True
                break

        if not has_cyrillic_name:
            return None

        # Область сканирования: фиксированная ширина слева от "Lv."
        # Римские цифры I/II/III/IV занимают ~5-35 пикселей на 540x960
        # Берём 45px запаса, чтобы точно захватить все штрихи
        scan_width = 45
        scan_x2 = lv_x_min - 2   # 2px отступ от Lv.
        scan_x1 = max(0, scan_x2 - scan_width)
        scan_y1 = lv_elem['y_min']
        scan_y2 = lv_elem['y_max']

        if scan_x2 - scan_x1 < 5:
            return None

        strokes = self._count_vertical_strokes(
            screenshot, scan_x1, scan_y1, scan_x2, scan_y2
        )

        if strokes > 0:
            result = self._strokes_to_roman(strokes, f"(область слева от Lv.)")

            if result:
                logger.info(f"🔧 Стратегия 2: обнаружено {strokes} штрихов "
                            f"в области [{scan_x1}-{scan_x2}]x[{scan_y1}-{scan_y2}] → '{result}'")

            return result

        return None

    def _strokes_to_roman(self, strokes: int, source_text: str = "") -> Optional[str]:
        """
        Преобразовать количество штрихов в римскую цифру.

        Args:
            strokes: Количество вертикальных штрихов
            source_text: Исходный текст OCR (для логирования)

        Returns:
            Римская цифра ("I", "II", "III", "IV") или None
        """
        roman_map = {1: "I", 2: "II", 3: "III", 4: "IV"}
        result = roman_map.get(strokes)

        if result is None:
            logger.warning(f"🔧 Необычное количество штрихов: {strokes}, "
                           f"источник: '{source_text}'")
            return None

        # Логируем только если произошла коррекция
        source_clean = source_text.strip()
        if source_clean and source_clean not in ("I", "II", "III", "IV") \
                and result != source_clean:
            logger.info(f"🔧 Коррекция римской цифры: '{source_clean}' → '{result}' "
                        f"(штрихов: {strokes})")

        return result

    # ==================== ПАРСИНГ ====================

    def parse_level(self, text: str) -> Optional[int]:
        """
        Парсинг уровня здания из текста (толерантен к ошибкам OCR)
        """
        patterns = [
            r'[LlЛл][vVуУyYвВ]\.?\s*(\d+)',
            r'Level\s*(\d+)',
            r'Ур\.?\s*(\d+)',
            r'уровень\s*(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def parse_timer(self, text: str) -> Optional[Dict[str, int]]:
        """
        Парсинг таймера из текста
        """
        patterns = [
            r'(\d{1,2}):(\d{2}):(\d{2})',
            r'(\d{1,2}):(\d{2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    hours, minutes, seconds = map(int, groups)
                else:
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
        """
        text = re.sub(r'[LlЛл][vVуУyYвВ]\.?\s*\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'[ПпPp][еeЕE][рpРP][еeЕE][йиĭІі][тtТT][иiІі]', '', text, flags=re.IGNORECASE)
        text = ' '.join(text.split())
        return text.strip()

    def group_by_rows(self, elements: List[Dict[str, Any]], y_threshold: int = 20) -> List[List[Dict[str, Any]]]:
        """
        Группировка элементов по строкам на основе Y-координат
        """
        if not elements:
            return []

        sorted_elements = sorted(elements, key=lambda e: e['y'])

        rows = []
        current_row = [sorted_elements[0]]

        for elem in sorted_elements[1:]:
            if abs(elem['y'] - current_row[0]['y']) <= y_threshold:
                current_row.append(elem)
            else:
                current_row.sort(key=lambda e: e['x'])
                rows.append(current_row)
                current_row = [elem]

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

        ИЗМЕНЕНИЕ v2: Добавлена двухуровневая коррекция римских цифр.
        1. Стратегия 1 — отдельный OCR-элемент (как раньше)
        2. Стратегия 2 — сканирование области слева от "Lv." (НОВОЕ)
        3. Если в имени нет римской цифры, но штрихи найдены — ДОБАВЛЯЕМ (НОВОЕ)

        Args:
            screenshot: Скриншот экрана
            emulator_id: ID эмулятора (для debug)

        Returns:
            Список зданий с координатами кнопки "Перейти"
        """
        elements = self.recognize_text(screenshot, min_confidence=0.3)

        if not elements:
            logger.warning("⚠️ OCR не распознал ни одного элемента")
            return []

        rows = self.group_by_rows(elements, y_threshold=20)

        buildings = []

        for row in rows:
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

            # Парсим название здания (из текста OCR)
            building_name = self.parse_building_name(row_text)

            if not building_name:
                continue

            # ═══════════════════════════════════════════════════
            # КОРРЕКЦИЯ РИМСКИХ ЦИФР через анализ изображения
            # ═══════════════════════════════════════════════════
            corrected_roman = self._correct_roman_numeral(screenshot, row)

            if corrected_roman:
                # Ищем римскую цифру в конце названия здания
                roman_pattern = re.search(r'\s+(I{1,4}|IV|V|VI{0,3})\s*$', building_name)

                if roman_pattern:
                    # Римская цифра ЕСТЬ — проверяем, нужна ли замена
                    ocr_roman = roman_pattern.group(1)

                    if ocr_roman != corrected_roman:
                        old_name = building_name
                        building_name = (building_name[:roman_pattern.start(1)]
                                         + corrected_roman
                                         + building_name[roman_pattern.end(1):])
                        building_name = building_name.strip()
                        logger.info(f"🔧 Исправлено название: '{old_name}' → '{building_name}'")
                else:
                    # Римской цифры НЕТ в имени (OCR проглотил полностью),
                    # но штрихи обнаружены — ДОБАВЛЯЕМ, только если > 1 штрих
                    # (одиночный штрих может быть артефактом шрифта)
                    if corrected_roman in ("II", "III", "IV"):
                        old_name = building_name
                        building_name = f"{building_name} {corrected_roman}"
                        logger.info(f"🔧 Добавлена римская цифра: '{old_name}' → '{building_name}'")

            # Координаты кнопки "Перейти"
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
                box = elem['bbox']
                if isinstance(box, np.ndarray):
                    box = box.astype(int)
                else:
                    box = np.array(box, dtype=int)

                cv2.polylines(debug_img, [box], True, (0, 255, 0), 2)

                text = elem['text']
                confidence = elem['confidence']
                label = f"{text} ({confidence:.2f})"

                if len(box) > 0:
                    x, y = int(box[0][0]), int(box[0][1]) - 5
                    cv2.putText(debug_img, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                              0.5, (0, 255, 0), 1, cv2.LINE_AA)

            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"emu1_navigation_{timestamp}.png"
            filepath = self.debug_dir / filename
            cv2.imwrite(str(filepath), debug_img)
            logger.info(f"🐛 Debug скриншот сохранён: {filepath}")

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения debug скриншота: {e}")