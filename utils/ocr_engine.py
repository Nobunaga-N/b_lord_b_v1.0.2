"""
OCR движок для распознавания текста в игре Beast Lord

Основан на PaddleOCR 3.x с поддержкой GPU
Адаптирован под русский язык и специфику игры

Версия: 3.0
Изменения v3: Template matching для римских цифр (замена stroke-counting)
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

# Базовая директория проекта (utils/ → корень)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class OCREngine:
    """
    OCR движок для распознавания текста (PaddleOCR 3.x)

    Features:
    - Автоматическое определение GPU/CPU
    - Русский язык (кириллица + латиница)
    - Парсинг уровней зданий (Lv.X)
    - Парсинг таймеров (HH:MM:SS)
    - Построчная группировка элементов
    - Коррекция римских цифр через template matching
    - Debug режим с сохранением bbox
    """

    # ==================== КОНСТАНТЫ: РИМСКИЕ ЦИФРЫ ====================

    # Здания, у которых бывает римская цифра в названии.
    # Template matching применяется ТОЛЬКО к ним (фильтр от ложных срабатываний).
    BUILDINGS_WITH_ROMAN = {
        "Центр Сбора",
        "Целебный Родник",
        "Полигон Зверей",
        "Походный Отряд",
        "Особый Отряд",
        "Поход Войска",
        "Склад Песка",
        "Склад Листьев",
        "Склад Грунта",
        "Склад Фруктов",
    }

    # Шаблоны римских цифр (вырезаны вручную из скриншота)
    ROMAN_TEMPLATE_PATHS = {
        "II": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'roman_II.png'),
        "III": os.path.join(BASE_DIR, 'data', 'templates', 'building', 'roman_III.png'),
    }

    # Порог совпадения для template matching римских цифр
    ROMAN_MATCH_THRESHOLD = 0.80

    # ==================== ИНИЦИАЛИЗАЦИЯ ====================

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
            raise RuntimeError(
                "PaddleOCR не установлен! "
                "Установите: pip install paddleocr paddlepaddle-gpu"
            )

        self.lang = lang
        self.debug_mode = False
        self.debug_dir = Path("data/screenshots/debug/ocr")
        self.debug_dir.mkdir(parents=True, exist_ok=True)

        # Lazy-loaded кэши для template matching римских цифр
        self._roman_templates = None  # Шаблоны roman_II / roman_III
        self._lv_template_cache = None  # Кэш шаблона "Lv." (per-screenshot)

        # Проверка GPU
        use_gpu = False
        if not force_cpu:
            try:
                use_gpu = paddle.device.is_compiled_with_cuda()
                if use_gpu:
                    gpu_count = paddle.device.cuda.device_count()
                    logger.info(
                        f"🎮 GPU обнаружен! "
                        f"Доступно устройств: {gpu_count}"
                    )
                else:
                    logger.warning(
                        "⚠️ GPU не обнаружен, используется CPU"
                    )
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка проверки GPU: {e}, используется CPU"
                )
                use_gpu = False
        else:
            logger.info("🔧 Принудительно используется CPU")

        # Инициализация PaddleOCR 3.x
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
                logger.success(
                    f"✅ OCR инициализирован "
                    f"(модель: eslav, устройство: {device})"
                )
            else:
                self.ocr = PaddleOCR(
                    lang=lang,
                    device=device,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                )
                logger.success(
                    f"✅ OCR инициализирован "
                    f"(язык: {lang}, устройство: {device})"
                )

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации OCR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    def set_debug_mode(self, enabled: bool):
        """Включить/выключить debug режим (сохранение скриншотов с bbox)"""
        self.debug_mode = enabled
        logger.info(f"🐛 Debug режим: {'ВКЛ' if enabled else 'ВЫКЛ'}")

    # ==================== НОРМАЛИЗАЦИЯ ТЕКСТА ====================

    def normalize_cyrillic_text(self, text: str) -> str:
        """
        Нормализация текста: заменяет визуально похожие
        латинские символы на кириллицу.

        Применяется к ВСЕМУ распознанному тексту,
        кроме аббревиатур уровней (Lv.).
        """
        # Сохраняем аббревиатуры уровней "Lv."
        level_match = re.search(
            r'[LlЛл][vVуУyYвВ]\.?\s*\d+', text, flags=re.IGNORECASE
        )
        level_text = level_match.group() if level_match else None

        replacements = {
            'y': 'у', 'p': 'р', 'c': 'с', 'o': 'о', 'a': 'а',
            'e': 'е', 'x': 'х', 'k': 'к',
            'B': 'В', 'H': 'Н', 'P': 'Р', 'C': 'С', 'T': 'Т',
            'Y': 'У', 'O': 'О', 'A': 'А', 'E': 'Е', 'X': 'Х',
            'K': 'К',
        }

        normalized = text
        for lat, cyr in replacements.items():
            normalized = normalized.replace(lat, cyr)

        if level_text:
            normalized_level = re.search(
                r'[LlЛл][vVуУyYвВ]\.?\s*\d+',
                normalized, flags=re.IGNORECASE
            )
            if normalized_level:
                normalized = normalized.replace(
                    normalized_level.group(), level_text
                )

        return normalized

    # ==================== РАСПОЗНАВАНИЕ ТЕКСТА ====================

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

            if hasattr(result, '__iter__') and \
               not isinstance(result, (list, dict)):
                result = list(result)
                logger.debug(
                    f"🔍 Converted generator to list, "
                    f"length: {len(result)}"
                )

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
                    logger.debug(
                        f"🔍 OCRResult keys: {list(ocr_result.keys())}"
                    )

                    if 'dt_polys' in ocr_result:
                        boxes = ocr_result['dt_polys']
                        logger.debug(
                            f"🔍 Found dt_polys: type={type(boxes)}, "
                            f"len={len(boxes)}"
                        )
                    if 'rec_texts' in ocr_result:
                        texts = ocr_result['rec_texts']
                        logger.debug(
                            f"🔍 Found rec_texts: type={type(texts)}, "
                            f"len={len(texts)}"
                        )
                    if 'rec_scores' in ocr_result:
                        scores = ocr_result['rec_scores']
                        logger.debug(
                            f"🔍 Found rec_scores: type={type(scores)}, "
                            f"len={len(scores)}"
                        )

                logger.debug(
                    f"📦 Final data - boxes: {boxes is not None}, "
                    f"texts: {texts is not None}, "
                    f"scores: {scores is not None}"
                )

                if texts is not None and boxes is not None \
                   and scores is not None:
                    try:
                        logger.debug(
                            f"📦 Найдено элементов: {len(texts)}"
                        )

                        for idx, (text, box, score) in enumerate(
                            zip(texts, boxes, scores)
                        ):
                            if score < min_confidence:
                                continue

                            if isinstance(box, np.ndarray):
                                xs = box[:, 0]
                                ys = box[:, 1]
                                x_min = int(np.min(xs))
                                x_max = int(np.max(xs))
                                y_min = int(np.min(ys))
                                y_max = int(np.max(ys))
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
                                'bbox': box.tolist()
                                    if isinstance(box, np.ndarray)
                                    else box,
                                'x': center_x,
                                'y': center_y,
                                'x_min': x1 + x_min,
                                'y_min': y1 + y_min,
                                'x_max': x1 + x_max,
                                'y_max': y1 + y_max,
                            })

                        logger.info(
                            f"📊 OCR распознал {len(elements)} элементов"
                        )
                    except Exception as e:
                        logger.error(
                            f"❌ Ошибка обработки результатов: {e}"
                        )
                        import traceback
                        logger.error(traceback.format_exc())

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга результатов: {e}")
            import traceback
            logger.error(traceback.format_exc())

        if self.debug_mode and elements:
            self._save_debug_screenshot(crop, elements, region)

        return elements

    # ==================== КОРРЕКЦИЯ РИМСКИХ ЦИФР (TEMPLATE MATCHING) ====================

    def _load_roman_templates(self) -> Dict[str, np.ndarray]:
        """
        Загрузить шаблоны римских цифр (lazy, grayscale).

        Загружает roman_II.png и roman_III.png один раз при первом вызове.
        Шаблон для "I" не нужен — одиночная I определяется по отсутствию
        совпадения с II и III (OCR обычно справляется с одиночной I).

        Returns:
            Dict[str, np.ndarray]: {"II": grayscale_img, "III": grayscale_img}
        """
        if self._roman_templates is not None:
            return self._roman_templates

        self._roman_templates = {}

        for name, path in self.ROMAN_TEMPLATE_PATHS.items():
            if not os.path.exists(path):
                logger.warning(
                    f"⚠️ Шаблон римской цифры не найден: {path}"
                )
                continue

            img = cv2.imread(path)
            if img is None:
                logger.warning(
                    f"⚠️ Не удалось загрузить шаблон: {path}"
                )
                continue

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) \
                if len(img.shape) == 3 else img
            self._roman_templates[name] = gray
            logger.debug(
                f"✅ Шаблон '{name}': "
                f"{gray.shape[1]}x{gray.shape[0]}px"
            )

        if self._roman_templates:
            logger.info(
                f"📐 Загружено шаблонов римских цифр: "
                f"{len(self._roman_templates)}"
            )
        else:
            logger.error(
                "❌ Шаблоны римских цифр не найдены! Создайте:\n"
                f"   {self.ROMAN_TEMPLATE_PATHS.get('II', '?')}\n"
                f"   {self.ROMAN_TEMPLATE_PATHS.get('III', '?')}"
            )

        return self._roman_templates

    def _build_lv_template(
        self,
        screenshot: np.ndarray,
        elements: List[Dict]
    ) -> Optional[np.ndarray]:
        """
        Извлечь шаблон "Lv." из отдельного OCR-элемента "Lv.X".

        Находит первый элемент вида "Lv.5", кропает левые ~65%
        (только "Lv." без цифры уровня), переводит в grayscale.

        Используется для точного позиционирования "Lv." внутри
        склеенных OCR-элементов через template matching.

        Args:
            screenshot: Полный скриншот (BGR)
            elements: Все OCR-элементы

        Returns:
            Grayscale шаблон "Lv." или None
        """
        for elem in elements:
            text = elem['text'].strip()

            # Ищем отдельный элемент "Lv.X" (без кириллицы)
            if re.match(r'^[LlЛл][vVуУyYвВ]\.?\s*\d+$', text) and \
               not re.search(r'[а-яА-ЯёЁ]', text):

                x1, y1 = elem['x_min'], elem['y_min']
                x2, y2 = elem['x_max'], elem['y_max']

                # Кропаем ~65% слева (только "Lv." без цифры)
                lv_width = int((x2 - x1) * 0.65)
                lv_x2 = x1 + lv_width

                crop = screenshot[y1:y2, x1:lv_x2]
                if crop.size == 0:
                    continue

                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) \
                    if len(crop.shape) == 3 else crop

                logger.debug(
                    f"📐 Шаблон Lv. из '{text}' "
                    f"размер={gray.shape[1]}x{gray.shape[0]}px"
                )
                return gray

        return None

    def _find_lv_pixel_x(
        self,
        screenshot: np.ndarray,
        elem: Dict,
        lv_template: np.ndarray,
        threshold: float = 0.6
    ) -> Optional[int]:
        """
        Найти пиксельную X-позицию "Lv." внутри OCR-элемента
        через template matching.

        Используется когда OCR склеил название и "Lv." в один элемент,
        например: "Центр Сбора II Lv.5"

        Args:
            screenshot: Полный скриншот
            elem: OCR-элемент (склеенный)
            lv_template: Grayscale шаблон "Lv."
            threshold: Порог совпадения

        Returns:
            Абсолютная X-координата начала "Lv." или None
        """
        x1, y1 = elem['x_min'], elem['y_min']
        x2, y2 = elem['x_max'], elem['y_max']

        crop = screenshot[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) \
            if len(crop.shape) == 3 else crop

        # Шаблон не должен быть больше области поиска
        if lv_template.shape[0] > gray.shape[0] or \
           lv_template.shape[1] > gray.shape[1]:
            return None

        result = cv2.matchTemplate(
            gray, lv_template, cv2.TM_CCOEFF_NORMED
        )
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            abs_x = x1 + max_loc[0]
            logger.debug(f"    Lv. match: x={abs_x} conf={max_val:.3f}")
            return abs_x

        return None

    def _find_lv_element(self, row: List[Dict]) -> Optional[Dict]:
        """
        Найти OCR-элемент содержащий "Lv.X" в строке.

        Поиск в два прохода:
        1. Отдельный элемент вида "Lv.5" (без кириллицы)
        2. Элемент содержащий "Lv." среди прочего текста

        Args:
            row: Список OCR-элементов одной строки

        Returns:
            OCR-элемент с "Lv." или None
        """
        # Проход 1: отдельный элемент
        for elem in row:
            text = elem['text'].strip()
            if re.match(r'^[LlЛл][vVуУyYвВ]\.?\s*\d+$', text) and \
               not re.search(r'[а-яА-ЯёЁ]', text):
                return elem

        # Проход 2: склеенный элемент
        for elem in row:
            if re.search(r'[LlЛл][vVуУyYвВ]\.?\s*\d+', elem['text']):
                return elem

        return None

    def _find_name_element(
        self,
        row: List[Dict],
        lv_elem: Dict
    ) -> Optional[Dict]:
        """
        Найти текстовый элемент с названием здания в строке.

        Два случая:
        1. Название и Lv. — разные OCR-элементы
           → берём кириллический элемент левее Lv.
        2. OCR склеил их вместе → возвращаем сам lv_elem

        Args:
            row: OCR-элементы строки
            lv_elem: Элемент с "Lv."

        Returns:
            Элемент с названием здания или None
        """
        # Случай 1: отдельный кириллический элемент левее Lv.
        candidates = []
        for elem in row:
            if elem is lv_elem:
                continue
            if elem['x_min'] >= lv_elem['x_min']:
                continue
            if re.search(r'[а-яА-ЯёЁ]', elem['text']):
                candidates.append(elem)

        if candidates:
            # Берём ближайший к Lv. (максимальный x_max)
            return max(candidates, key=lambda e: e['x_max'])

        # Случай 2: склеенный — сам lv_elem содержит и название
        if re.search(r'[а-яА-ЯёЁ]', lv_elem['text']):
            return lv_elem

        return None

    def _extract_roman_zone(
        self,
        screenshot: np.ndarray,
        name_elem: Dict,
        lv_elem: Dict,
        lv_template: Optional[np.ndarray] = None,
        roman_width: int = 35,
        padding: int = 2
    ) -> Optional[np.ndarray]:
        """
        Вырезать зону слева от "Lv." где находится римская цифра.

        Два сценария:
        1. Раздельные элементы (name_elem ≠ lv_elem)
           → зона между name и Lv.
        2. Склеенный элемент
           → ищем "Lv." через template matching, кропаем 35px левее

        Args:
            screenshot: Полный скриншот
            name_elem: OCR-элемент с названием
            lv_elem: OCR-элемент с "Lv."
            lv_template: Шаблон "Lv." для template matching
            roman_width: Ширина зоны поиска (px)
            padding: Вертикальный отступ (px)

        Returns:
            Кроп зоны с римской цифрой или None
        """
        h, w = screenshot.shape[:2]

        # Случай 1: РАЗДЕЛЬНЫЕ элементы
        if name_elem is not lv_elem and \
           name_elem['x_max'] < lv_elem['x_min']:
            x2 = min(w, lv_elem['x_min'] + 2)
            x1 = max(0, x2 - roman_width)
            y1 = max(
                0,
                min(name_elem['y_min'], lv_elem['y_min']) - padding
            )
            y2 = min(
                h,
                max(name_elem['y_max'], lv_elem['y_max']) + padding
            )

            crop = screenshot[y1:y2, x1:x2]
            return crop if crop.size > 0 else None

        # Случай 2: СКЛЕЕННЫЙ → ищем "Lv." через template matching
        lv_x = None
        if lv_template is not None:
            lv_x = self._find_lv_pixel_x(
                screenshot, name_elem, lv_template
            )

        # Fallback: пропорционально по тексту
        if lv_x is None:
            text = name_elem['text']
            lv_match = re.search(r'[LlЛл][vVуУyYвВ]', text)
            if lv_match:
                ratio = lv_match.start() / max(len(text), 1)
                elem_w = name_elem['x_max'] - name_elem['x_min']
                lv_x = name_elem['x_min'] + int(elem_w * ratio)
                logger.debug(
                    f"    Lv. fallback: x={lv_x} (ratio={ratio:.2f})"
                )

        if lv_x is None:
            return None

        gap = 2
        x2 = min(w, lv_x - gap)
        x1 = max(0, x2 - roman_width)
        y1 = max(0, name_elem['y_min'] - padding)
        y2 = min(h, name_elem['y_max'] + padding)

        if x2 - x1 < 5:
            return None

        crop = screenshot[y1:y2, x1:x2]
        return crop if crop.size > 0 else None

    def _match_roman_in_zone(
        self,
        zone_crop: np.ndarray
    ) -> Tuple[Optional[str], float]:
        """
        Найти римскую цифру в зоне через template matching.

        Сравнивает кроп с шаблонами roman_II.png и roman_III.png.
        Возвращает лучшее совпадение выше ROMAN_MATCH_THRESHOLD.

        Args:
            zone_crop: Кроп зоны (BGR или grayscale)

        Returns:
            (matched_roman, confidence): ("II", 0.92) или (None, 0.0)
        """
        if zone_crop is None or zone_crop.size == 0:
            return None, 0.0

        templates = self._load_roman_templates()
        if not templates:
            return None, 0.0

        gray = cv2.cvtColor(zone_crop, cv2.COLOR_BGR2GRAY) \
            if len(zone_crop.shape) == 3 else zone_crop

        best_name = None
        best_conf = 0.0

        for name, tmpl in templates.items():
            # Шаблон не должен быть больше зоны поиска
            if tmpl.shape[0] > gray.shape[0] or \
               tmpl.shape[1] > gray.shape[1]:
                continue

            result = cv2.matchTemplate(
                gray, tmpl, cv2.TM_CCOEFF_NORMED
            )
            _, max_val, _, _ = cv2.minMaxLoc(result)

            if max_val > best_conf:
                best_conf = max_val
                best_name = name

        if best_conf >= self.ROMAN_MATCH_THRESHOLD:
            return best_name, best_conf

        return None, best_conf

    def _correct_roman_numeral(
        self,
        screenshot: np.ndarray,
        row: List[Dict[str, Any]],
        lv_template: Optional[np.ndarray] = None
    ) -> Optional[str]:
        """
        Определить римскую цифру в строке здания через template matching.

        Алгоритм:
        1. Найти элемент "Lv." в строке
        2. Найти элемент с названием здания
        3. Вырезать зону слева от "Lv." (там римская цифра)
        4. Template matching кропа vs roman_II.png / roman_III.png
        5. Вернуть результат ("II", "III") или None

        Args:
            screenshot: Полный скриншот (BGR)
            row: Список OCR-элементов одной строки
            lv_template: Предварительно построенный шаблон "Lv."
                         (передаётся из parse_navigation_panel)

        Returns:
            Скорректированная римская цифра ("II", "III") или None
            (None = нет совпадения с шаблонами, оставить как есть)
        """
        # 1. Найти элемент "Lv." в строке
        lv_elem = self._find_lv_element(row)
        if lv_elem is None:
            return None

        # 2. Найти элемент с названием здания
        name_elem = self._find_name_element(row, lv_elem)
        if name_elem is None:
            return None

        # 3. Вырезать зону где должна быть римская цифра
        zone_crop = self._extract_roman_zone(
            screenshot, name_elem, lv_elem, lv_template
        )

        if zone_crop is None or zone_crop.shape[1] < 5:
            return None

        # 4. Template matching
        matched_roman, confidence = self._match_roman_in_zone(zone_crop)

        if matched_roman:
            logger.debug(
                f"🔧 Template match: '{matched_roman}' "
                f"conf={confidence:.3f}"
            )

        return matched_roman

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
        Парсинг названия здания
        (убирает уровни и кнопки, но сохраняет римские цифры)
        """
        text = re.sub(
            r'[LlЛл][vVуУyYвВ]\.?\s*\d+', '', text,
            flags=re.IGNORECASE
        )
        text = re.sub(
            r'[ПпPp][еeЕE][рpРP][еeЕE][йиĭІі][тtТT][иiІі]', '',
            text, flags=re.IGNORECASE
        )
        text = ' '.join(text.split())
        return text.strip()

    def group_by_rows(
        self,
        elements: List[Dict[str, Any]],
        y_threshold: int = 20
    ) -> List[List[Dict[str, Any]]]:
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

    # ==================== ПАРСИНГ ПАНЕЛИ НАВИГАЦИИ ====================

    def parse_navigation_panel(
        self,
        screenshot: np.ndarray,
        emulator_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Полный парсинг панели навигации (список зданий)

        v3: Template matching для римских цифр.
        - Шаблон "Lv." строится ОДИН РАЗ перед циклом
        - Template matching применяется ТОЛЬКО к зданиям
          из BUILDINGS_WITH_ROMAN
        - Шаблоны roman_II / roman_III загружаются лениво

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

        # Построить шаблон "Lv." ОДИН РАЗ для всего скриншота
        lv_template = self._build_lv_template(screenshot, elements)
        if lv_template is not None:
            logger.debug(
                f"📐 Шаблон Lv.: "
                f"{lv_template.shape[1]}x{lv_template.shape[0]}px"
            )

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
                re.search(
                    r'[ПпPp][еeЕE][рpРP][еeЕE][йиĭІі][тtТT][иiІі]',
                    elem['text'], re.IGNORECASE
                )
                for elem in row
            )

            if not has_button:
                continue

            # Парсим название здания (из текста OCR)
            building_name = self.parse_building_name(row_text)

            if not building_name:
                continue

            # ═══════════════════════════════════════════════════
            # КОРРЕКЦИЯ РИМСКИХ ЦИФР через template matching
            # Применяется ТОЛЬКО к зданиям из BUILDINGS_WITH_ROMAN
            # ═══════════════════════════════════════════════════
            needs_roman_check = any(
                base in building_name
                for base in self.BUILDINGS_WITH_ROMAN
            )

            corrected_roman = None
            if needs_roman_check:
                corrected_roman = self._correct_roman_numeral(
                    screenshot, row, lv_template
                )

            if corrected_roman:
                # Ищем римскую цифру в конце названия здания
                roman_pattern = re.search(
                    r'\s+(I{1,4}|IV|V|VI{0,3})\s*$', building_name
                )

                if roman_pattern:
                    # Римская есть — проверяем нужна ли замена
                    ocr_roman = roman_pattern.group(1)

                    if ocr_roman != corrected_roman:
                        old_name = building_name
                        building_name = (
                            building_name[:roman_pattern.start(1)]
                            + corrected_roman
                            + building_name[roman_pattern.end(1):]
                        )
                        building_name = building_name.strip()
                        logger.info(
                            f"🔧 Template коррекция: "
                            f"'{old_name}' → '{building_name}'"
                        )
                else:
                    # Римской НЕТ — OCR проглотил полностью
                    # Добавляем только II/III/IV (не I)
                    if corrected_roman in ("II", "III", "IV"):
                        old_name = building_name
                        building_name = (
                            f"{building_name} {corrected_roman}"
                        )
                        logger.info(
                            f"🔧 Template добавлено: "
                            f"'{old_name}' → '{building_name}'"
                        )

            # Координаты кнопки "Перейти"
            button_elem = row[-1]
            button_y = button_elem['y']

            buildings.append({
                'name': building_name,
                'level': level,
                'y': button_y,
                'raw_text': row_text
            })

            logger.info(
                f"✅ Здание: {building_name} Lv.{level} (Y: {button_y})"
            )

        return buildings

    # ==================== DEBUG ====================

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
                    cv2.putText(
                        debug_img, label, (x, y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 0), 1, cv2.LINE_AA
                    )

            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"emu1_navigation_{timestamp}.png"
            filepath = self.debug_dir / filename
            cv2.imwrite(str(filepath), debug_img)
            logger.info(f"🐛 Debug скриншот сохранён: {filepath}")

        except Exception as e:
            logger.error(
                f"❌ Ошибка сохранения debug скриншота: {e}"
            )