"""
Парсер ускорений из Рюкзака (вкладка "Ускорение")

Рюкзак содержит ВСЕ ускорения эмулятора в виде сетки 4×6.
Каждая ячейка: иконка типа + метка номинала + количество.

Определение:
  - Тип ускорения  → template matching (universal/evolution/training/building)
  - Номинал        → OCR (raw crop, scale 5x, чёрные поля)
  - Количество     → OCR (raw crop, scale 5x, чёрные поля)

Шаблоны загружаются из:
  data/templates/speedups/backpack/types/   — type_{name}[_{variant}].png

Версия: 2.0 — denom через OCR вместо template matching
"""

import os
import re
import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple

from utils.logger import logger
from utils.ocr_engine import OCREngine

# ═══════════════════════════════════════════════════
# ПУТИ К ШАБЛОНАМ
# ═══════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'data', 'templates', 'speedups', 'backpack')
TYPE_TEMPLATE_DIR = os.path.join(TEMPLATE_DIR, 'types')

# ═══════════════════════════════════════════════════
# СЕТКА РЮКЗАКА (540×960, вкладка "Ускорение")
# 4 столбца × 6 рядов = 24 ячейки на экране
# ═══════════════════════════════════════════════════

GRID_COLS = [
    (15,  131),   # Столбец 0
    (150, 264),   # Столбец 1
    (281, 398),   # Столбец 2
    (415, 532),   # Столбец 3
]

GRID_ROWS = [
    (126, 240),   # Ряд 0
    (264, 375),   # Ряд 1
    (403, 515),   # Ряд 2
    (538, 652),   # Ряд 3
    (679, 789),   # Ряд 4
    (816, 928),   # Ряд 5
]

# ═══════════════════════════════════════════════════
# ЗОНЫ ВНУТРИ ЯЧЕЙКИ (относительно верхнего-левого угла)
# ═══════════════════════════════════════════════════

DENOM_ZONE = {'x1': 22, 'y1': 0, 'x2': 91, 'y2': 26}
TYPE_ZONE = {'x1': 4, 'y1': 16, 'x2': 114, 'y2': 89}
QTY_ZONE = {'x1': 0, 'y1': 88, 'x2': 114, 'y2': 110}

# OCR параметры для количества
QTY_SCALE = 5
QTY_PADDING = 25

# OCR параметры для номинала
DENOM_SCALE = 5
DENOM_PADDING = 20

# Порог template matching (только тип)
THRESHOLD_TYPE = 0.70

# Конвертация номиналов в секунды
DENOM_SECONDS = {
    '1m': 60, '5m': 300, '10m': 600, '15m': 900,
    '1h': 3600, '2h': 7200, '3h': 10800, '8h': 28800,
    '1d': 86400, '5d': 432000,
}

DENOM_ORDER = ['1m', '5m', '10m', '15m', '1h', '2h', '3h', '8h', '1d', '5d']

VALID_DENOMS = set(DENOM_ORDER)

# Кеш шаблонов типов (загружаются один раз за сессию)
_type_templates_cache: Optional[Dict] = None


# ═══════════════════════════════════════════════════
# ПУБЛИЧНЫЙ API
# ═══════════════════════════════════════════════════

def parse_backpack_speedups(
    screenshot: np.ndarray,
    ocr: OCREngine
) -> Dict[str, Dict[str, int]]:
    """
    Парсинг одного экрана рюкзака (без свайпа).

    Для каждой ячейки сетки:
    1. Template match ТИП
    2. OCR НОМИНАЛ
    3. OCR КОЛИЧЕСТВО

    Args:
        screenshot: скриншот экрана 540×960
        ocr: инициализированный OCREngine

    Returns:
        {speedup_type: {denomination: quantity}}
        Пример: {'universal': {'1h': 26, '5m': 140}, 'building': {'15m': 12}}
    """
    type_templates = _get_type_templates()

    if not type_templates:
        logger.error(f"❌ Нет шаблонов типов в {TYPE_TEMPLATE_DIR}/")
        return {}

    h, w = screenshot.shape[:2]
    result: Dict[str, Dict[str, int]] = {}
    parsed_count = 0

    for row in range(len(GRID_ROWS)):
        for col in range(len(GRID_COLS)):
            x1, y1, x2, y2 = _get_cell_bounds(col, row)

            if y2 > h:
                continue

            cell = screenshot[y1:y2, x1:x2]
            if cell.size == 0:
                continue

            label = f"r{row}_c{col}"

            # 1. Template match ТИП
            type_crop = _crop_zone(cell, TYPE_ZONE)
            type_match = _match_best_template(
                type_crop, type_templates, THRESHOLD_TYPE
            )

            if type_match is None:
                continue  # Пустая ячейка

            stype, type_conf = type_match

            # 2. OCR НОМИНАЛ
            denom_crop = _crop_zone(cell, DENOM_ZONE)
            denom = _ocr_denomination(denom_crop, ocr, label)

            if denom is None:
                logger.warning(
                    f"  [{label}] тип={stype}({type_conf:.2f}), "
                    f"но номинал OCR не распознал"
                )
                continue

            # 3. OCR КОЛИЧЕСТВО
            qty_crop = _crop_zone(cell, QTY_ZONE)
            qty = _ocr_quantity(qty_crop, ocr)

            if qty is None:
                logger.warning(
                    f"  [{label}] {stype}/{denom} — "
                    f"OCR не распознал количество"
                )
                continue

            # Сохраняем результат
            if stype not in result:
                result[stype] = {}
            result[stype][denom] = qty
            parsed_count += 1

    logger.info(f"📦 Рюкзак: распознано {parsed_count} типов ускорений")
    return result


def get_total_seconds_from_parsed(
    parsed: Dict[str, Dict[str, int]],
    speedup_type: Optional[str] = None
) -> int:
    """
    Подсчитать общее кол-во секунд ускорений.

    Args:
        parsed: результат parse_backpack_speedups()
        speedup_type: фильтр по типу (None = все)

    Returns:
        int: суммарные секунды
    """
    total = 0
    for stype, denoms in parsed.items():
        if speedup_type and stype != speedup_type:
            continue
        for denom, qty in denoms.items():
            total += DENOM_SECONDS.get(denom, 0) * qty
    return total


# ═══════════════════════════════════════════════════
# КЕШИРОВАНИЕ ШАБЛОНОВ
# ═══════════════════════════════════════════════════

def _get_type_templates() -> Dict[str, List[Tuple[str, np.ndarray]]]:
    """Загрузить и закешировать шаблоны типов"""
    global _type_templates_cache
    if _type_templates_cache is None:
        _type_templates_cache = _load_templates_from_dir(
            TYPE_TEMPLATE_DIR, "type"
        )
    return _type_templates_cache


# ═══════════════════════════════════════════════════
# ЗАГРУЗКА ШАБЛОНОВ
# ═══════════════════════════════════════════════════

def _load_templates_from_dir(
    directory: str,
    prefix: str
) -> Dict[str, List[Tuple[str, np.ndarray]]]:
    """
    Автозагрузка шаблонов из папки.

    Имя файла: {prefix}_{name}.png или {prefix}_{name}_{variant}.png
    Примеры:
      type_universal.png        → тип 'universal'
      type_universal_purple.png → тип 'universal' (вариант)

    Returns:
        {name: [(filename, cv2_image), ...]}
    """
    templates: Dict[str, List[Tuple[str, np.ndarray]]] = {}

    if not os.path.isdir(directory):
        logger.warning(f"⚠️ Папка шаблонов не найдена: {directory}")
        return templates

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith('.png'):
            continue
        if not filename.startswith(f"{prefix}_"):
            continue

        filepath = os.path.join(directory, filename)
        img = cv2.imread(filepath)
        if img is None:
            logger.warning(f"⚠️ Не удалось загрузить: {filename}")
            continue

        # Парсим имя: type_universal_purple.png → name='universal'
        stem = os.path.splitext(filename)[0]
        after_prefix = stem[len(prefix) + 1:]
        parts = after_prefix.split('_')
        name = parts[0]

        if name not in templates:
            templates[name] = []
        templates[name].append((filename, img))

    total = sum(len(v) for v in templates.values())
    logger.debug(
        f"📂 Загружено {total} шаблонов из {os.path.basename(directory)}/ "
        f"({len(templates)} уникальных)"
    )
    return templates


# ═══════════════════════════════════════════════════
# TEMPLATE MATCHING
# ═══════════════════════════════════════════════════

def _match_best_template(
    crop: np.ndarray,
    templates: Dict[str, List[Tuple[str, np.ndarray]]],
    threshold: float
) -> Optional[Tuple[str, float]]:
    """
    Найти лучший шаблон среди набора (с вариантами).

    Returns:
        (best_name, confidence) или None
    """
    if crop.size == 0:
        return None

    best_name = None
    best_conf = 0.0

    for name, variants in templates.items():
        for filename, template in variants:
            if (template.shape[0] > crop.shape[0] or
                    template.shape[1] > crop.shape[1]):
                continue

            result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)

            if max_val > best_conf:
                best_conf = max_val
                best_name = name

    if best_name and best_conf >= threshold:
        return (best_name, best_conf)

    return None


# ═══════════════════════════════════════════════════
# OCR НОМИНАЛА
# ═══════════════════════════════════════════════════

def _ocr_denomination(
    crop: np.ndarray,
    ocr: OCREngine,
    label: str = ""
) -> Optional[str]:
    """
    OCR номинала из кропа: scale 5x → чёрные поля → PaddleOCR.

    Ожидаемые значения: 1m, 5m, 10m, 15m, 1h, 2h, 3h, 8h, 1d, 5d

    Returns:
        Валидный denom ('15m', '1h', ...) или None
    """
    if crop.size == 0:
        return None

    enlarged = cv2.resize(crop, None, fx=DENOM_SCALE, fy=DENOM_SCALE,
                          interpolation=cv2.INTER_CUBIC)
    padded = cv2.copyMakeBorder(
        enlarged, DENOM_PADDING, DENOM_PADDING, DENOM_PADDING, DENOM_PADDING,
        cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )

    elements = ocr.recognize_text(padded, min_confidence=0.2)

    # Пробуем каждый элемент
    for elem in elements:
        text = elem['text'].strip()
        denom = _try_parse_denom(text)
        if denom is not None:
            logger.debug(
                f"  [{label}] OCR denom={denom} (raw='{text}')"
            )
            return denom

    # Если отдельные элементы не подошли — склеиваем всё в одну строку
    if len(elements) > 1:
        full_text = ''.join(e['text'].strip() for e in elements)
        denom = _try_parse_denom(full_text)
        if denom is not None:
            logger.debug(
                f"  [{label}] OCR denom={denom} (merged='{full_text}')"
            )
            return denom

    if elements:
        texts = [e['text'] for e in elements]
        logger.warning(f"  [{label}] OCR denom FAIL: {texts}")
    else:
        logger.warning(f"  [{label}] OCR denom FAIL: пусто")

    return None


def _try_parse_denom(text: str) -> Optional[str]:
    """
    Распознать текст как номинал ускорения.

    Формат: {число}{единица}, где единица = m/h/d
    OCR может вернуть: "15m", "1h", "5d", а также мусор.

    Фиксы:
      - Кириллические замены единиц: 'т'→'m', 'м'→'m', 'ч'→'h', 'д'→'d'
      - Цифровые фиксы: 'г'→1, 'б'→6, 'з'→3 и т.д.
      - Удаление пробелов: "1 5m" → "15m"
    """
    cleaned = text.strip().lower()

    # Убираем пробелы внутри (OCR может разбить "15m" на "1 5m")
    cleaned = cleaned.replace(' ', '')

    # Кириллические замены единиц
    UNIT_FIXES = {
        'т': 'm', 'м': 'm', 'п': 'm',  # м/т/п → m (минуты)
        'ч': 'h',                         # ч → h (часы)
        'д': 'd',                         # д → d (дни)
    }
    if cleaned and cleaned[-1] in UNIT_FIXES:
        cleaned = cleaned[:-1] + UNIT_FIXES[cleaned[-1]]

    # Фикс цифр: OCR путает кириллицу с цифрами
    DIGIT_FIXES = {
        'г': '1', 'i': '1', 'l': '1', '|': '1',
        'б': '6', 'в': '8', 'з': '3', 'о': '0',
        'ч': '4', 'ь': '6', 'э': '9',
    }

    # Применяем фиксы к цифровой части (все кроме последнего символа)
    if len(cleaned) >= 2:
        digits_part = cleaned[:-1]
        unit_part = cleaned[-1]
        fixed_digits = ''
        for ch in digits_part:
            if ch in DIGIT_FIXES:
                fixed_digits += DIGIT_FIXES[ch]
            elif ch.isdigit():
                fixed_digits += ch
            # Пропускаем прочий мусор
        cleaned = fixed_digits + unit_part

    # Извлекаем паттерн {цифры}{m|h|d}
    match = re.match(r'^(\d{1,2})([mhd])$', cleaned)
    if match:
        num = match.group(1)
        unit = match.group(2)
        candidate = f"{num}{unit}"
        if candidate in VALID_DENOMS:
            return candidate

    return None


# ═══════════════════════════════════════════════════
# OCR КОЛИЧЕСТВА
# ═══════════════════════════════════════════════════

def _ocr_quantity(
    crop: np.ndarray,
    ocr: OCREngine
) -> Optional[int]:
    """
    OCR количества из кропа: scale 5x → чёрные поля → PaddleOCR.
    """
    if crop.size == 0:
        return None

    enlarged = cv2.resize(
        crop, None, fx=QTY_SCALE, fy=QTY_SCALE,
        interpolation=cv2.INTER_CUBIC
    )
    padded = cv2.copyMakeBorder(
        enlarged, QTY_PADDING, QTY_PADDING, QTY_PADDING, QTY_PADDING,
        cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )

    elements = ocr.recognize_text(padded, min_confidence=0.2)

    for elem in elements:
        text = elem['text'].strip()
        qty = _try_parse_quantity(text)
        if qty is not None:
            return qty

    return None


def _try_parse_quantity(text: str) -> Optional[int]:
    """
    Распознать текст как число количества.
    Включает фикс для однозначных чисел, которые OCR
    читает как кириллические буквы.
    """
    cleaned = text.strip()

    # Фикс: OCR путает одиночные цифры с кириллицей
    SINGLE_DIGIT_FIXES = {
        'г': '1', 'i': '1', 'l': '1', '|': '1',
        'б': '6', 'в': '8', 'з': '3', 'о': '0',
        'ч': '4', 'ь': '6', 'э': '9',
    }
    if len(cleaned) == 1 and cleaned in SINGLE_DIGIT_FIXES:
        return int(SINGLE_DIGIT_FIXES[cleaned])

    cleaned = re.sub(r'^[^0-9]+', '', cleaned)
    cleaned = re.sub(r'[^0-9]+$', '', cleaned)
    cleaned = cleaned.replace(',', '').replace('.', '')

    if cleaned.isdigit() and len(cleaned) <= 6:
        return int(cleaned)
    return None


# ═══════════════════════════════════════════════════
# УТИЛИТЫ СЕТКИ
# ═══════════════════════════════════════════════════

def _get_cell_bounds(col: int, row: int) -> Tuple[int, int, int, int]:
    """Абсолютные координаты ячейки (x1, y1, x2, y2)."""
    x1, x2 = GRID_COLS[col]
    y1, y2 = GRID_ROWS[row]
    return (x1, y1, x2, y2)


def _crop_zone(cell: np.ndarray, zone: dict) -> np.ndarray:
    """Вырезать зону из ячейки по относительным координатам."""
    h, w = cell.shape[:2]
    x1 = max(0, zone['x1'])
    y1 = max(0, zone['y1'])
    x2 = min(w, zone['x2'])
    y2 = min(h, zone['y2'])
    return cell[y1:y2, x1:x2]