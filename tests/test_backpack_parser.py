"""
Тест парсинга ускорений из Рюкзака (вкладка "Ускорение")

Рюкзак содержит ВСЕ ускорения эмулятора в виде сетки 4×N.
Каждая ячейка: иконка типа + метка номинала + количество.

Определение:
  - Тип ускорения  → template matching (universal/evolution/training/building)
  - Номинал        → template matching (1m/5m/15m/1h/2h/8h/5d)
  - Количество     → OCR (raw crop, scale 5x, чёрные поля)

Режимы:
  --extract    Диагностика: сохраняет полный скриншот + нарезанные ячейки
               и зоны (тип/номинал/количество) для ручной нарезки шаблонов
  --parse      Полный парсинг (2 прохода со свайпом) + template match + OCR
  --single     Один проход без свайпа (быстрая итерация)

Шаблоны: data/templates/speedups/backpack/types/ и denoms/

Запуск:
  python tests/test_backpack_parser.py --extract
  python tests/test_backpack_parser.py --parse
  python tests/test_backpack_parser.py --single

Эмулятор: ID=1, порт=5556 (переопределить: --id / --port)

Версия: 1.0
"""

import sys
import re
import cv2
import time
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════
# Пути проекта
# ═══════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import logger
from utils.ocr_engine import OCREngine
from utils.image_recognition import get_screenshot
from utils.adb_controller import swipe

# ═══════════════════════════════════════════════════
# НАСТРОЙКИ ЭМУЛЯТОРА
# ═══════════════════════════════════════════════════

DEFAULT_EMULATOR_ID = 7
DEFAULT_EMULATOR_PORT = 5568

DEBUG_DIR = PROJECT_ROOT / "data" / "screenshots" / "debug" / "backpack_parser"

# Шаблоны
TEMPLATE_DIR = PROJECT_ROOT / "data" / "templates" / "speedups" / "backpack"
TYPE_TEMPLATE_DIR = TEMPLATE_DIR / "types"
DENOM_TEMPLATE_DIR = TEMPLATE_DIR / "denoms"

# ═══════════════════════════════════════════════════
# СЕТКА РЮКЗАКА (540×960, вкладка "Ускорение")
#
# Предварительные значения — уточняются через --extract.
# Ячейки расположены в 4 столбца × N строк.
# ═══════════════════════════════════════════════════

# Границы столбцов (x1, x2) для каждого из 4 столбцов
GRID_COLS = [
    (15,  131),   # Столбец 0
    (150, 264),   # Столбец 1
    (281, 398),   # Столбец 2
    (415, 532),   # Столбец 3
]

# Границы строк (y1, y2) — неравномерные, захардкожены
# 6 рядов × 4 столбца = 24 ячейки на экране
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
#
# ┌──────────────────────┐
# │ [1h]          (тип)  │  ← denom_zone: верх-лево
# │                      │
# │    ⏩⏩  (иконка)     │  ← type_zone: центр
# │                      │
# │  [26]                │  ← qty_zone: низ-центр
# └──────────────────────┘
# ═══════════════════════════════════════════════════

# Зона номинала (метка "1m", "5m", "10m", "15m", "1h" и т.д.)
DENOM_ZONE = {
    'x1': 28,   'y1': 3,
    'x2': 85,  'y2': 20,
}

# Зона иконки типа (центральная часть)
TYPE_ZONE = {
    'x1': 8,   'y1': 20,
    'x2': 110, 'y2': 85,
}

# Зона количества (крупные белые цифры внизу)
QTY_ZONE = {
    'x1': 0,   'y1': 88,
    'x2': 114, 'y2': 110,
}

# OCR параметры для количества
QTY_SCALE = 5             # Масштаб увеличения для OCR
QTY_PADDING = 25          # Чёрные поля вокруг кропа

# ═══════════════════════════════════════════════════
# СВАЙПЫ
# ═══════════════════════════════════════════════════

SWIPE_DOWN = (270, 880, 270, 200, 600)   # Прокрутка вниз
SWIPE_UP   = (270, 200, 270, 880, 600)   # Возврат вверх

# ═══════════════════════════════════════════════════
# TEMPLATE MATCHING — маппинг шаблонов
# ═══════════════════════════════════════════════════

TYPE_TEMPLATES = {
    'universal':  TYPE_TEMPLATE_DIR / "type_universal.png",
    'evolution':  TYPE_TEMPLATE_DIR / "type_evolution.png",
    'training':   TYPE_TEMPLATE_DIR / "type_training.png",
    'building':   TYPE_TEMPLATE_DIR / "type_building.png",
}

DENOM_TEMPLATES = {
    '1m':  DENOM_TEMPLATE_DIR / "denom_1m.png",
    '5m':  DENOM_TEMPLATE_DIR / "denom_5m.png",
    '10m': DENOM_TEMPLATE_DIR / "denom_10m.png",
    '15m': DENOM_TEMPLATE_DIR / "denom_15m.png",
    '1h':  DENOM_TEMPLATE_DIR / "denom_1h.png",
    '2h':  DENOM_TEMPLATE_DIR / "denom_2h.png",
    '3h':  DENOM_TEMPLATE_DIR / "denom_3h.png",
    '8h':  DENOM_TEMPLATE_DIR / "denom_8h.png",
    '5d':  DENOM_TEMPLATE_DIR / "denom_5d.png",
}

# Пороги template matching
THRESHOLD_TYPE = 0.70
THRESHOLD_DENOM = 0.70

# Номинал → секунды
DENOM_SECONDS = {
    '1m': 60, '5m': 300, '10m': 600, '15m': 900,
    '1h': 3600, '2h': 7200, '3h': 10800, '8h': 28800, '5d': 432000,
}

DENOM_ORDER = ['1m', '5m', '10m', '15m', '1h', '2h', '3h', '8h', '5d']


# ═══════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════

def get_emulator(emu_id: int, port: int) -> dict:
    return {"id": emu_id, "name": f"test_backpack_{emu_id}", "port": port}


def ensure_debug_dir():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def get_cell_bounds(col: int, row: int) -> Tuple[int, int, int, int]:
    """
    Получить абсолютные координаты ячейки (x1, y1, x2, y2).

    Args:
        col: индекс столбца (0-3)
        row: индекс строки (0-5)

    Returns:
        (x1, y1, x2, y2) — абсолютные пиксельные координаты
    """
    x1, x2 = GRID_COLS[col]
    y1, y2 = GRID_ROWS[row]
    return (x1, y1, x2, y2)


def crop_zone(cell: np.ndarray, zone: dict) -> np.ndarray:
    """Вырезать зону из ячейки по относительным координатам."""
    h, w = cell.shape[:2]
    x1 = max(0, zone['x1'])
    y1 = max(0, zone['y1'])
    x2 = min(w, zone['x2'])
    y2 = min(h, zone['y2'])
    return cell[y1:y2, x1:x2]


def try_parse_quantity(text: str) -> Optional[int]:
    """
    Распознать текст как число количества.
    Убираем ведущие/завершающие не-цифры, парсим.
    """
    cleaned = text.strip()
    cleaned = re.sub(r'^[^0-9]+', '', cleaned)
    cleaned = re.sub(r'[^0-9]+$', '', cleaned)
    cleaned = cleaned.replace(',', '').replace('.', '')

    if cleaned.isdigit() and len(cleaned) <= 6:
        return int(cleaned)
    return None


def ocr_quantity(crop: np.ndarray, ocr: OCREngine,
                 label: str = "") -> Optional[int]:
    """
    OCR количества из кропа: scale 5x → чёрные поля → PaddleOCR.
    """
    if crop.size == 0:
        return None

    enlarged = cv2.resize(crop, None, fx=QTY_SCALE, fy=QTY_SCALE,
                          interpolation=cv2.INTER_CUBIC)
    padded = cv2.copyMakeBorder(
        enlarged, QTY_PADDING, QTY_PADDING, QTY_PADDING, QTY_PADDING,
        cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )

    elements = ocr.recognize_text(padded, min_confidence=0.2)

    for elem in elements:
        text = elem['text'].strip()
        qty = try_parse_quantity(text)
        if qty is not None:
            logger.debug(f"  [{label}] OCR qty={qty} (raw='{text}')")
            return qty

    if elements:
        texts = [e['text'] for e in elements]
        logger.debug(f"  [{label}] OCR не число: {texts}")

    return None


def match_best_template(crop: np.ndarray,
                        templates: Dict[str, Path],
                        threshold: float
                        ) -> Optional[Tuple[str, float]]:
    """
    Template matching: найти лучший шаблон среди набора.

    Args:
        crop: изображение (BGR)
        templates: {name: path_to_template}
        threshold: минимальный порог

    Returns:
        (best_name, confidence) или None
    """
    if crop.size == 0:
        return None

    best_name = None
    best_conf = 0.0

    for name, path in templates.items():
        if not path.exists():
            continue

        template = cv2.imread(str(path))
        if template is None:
            continue

        # Проверяем размеры
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


def denom_sort_key(item):
    d = item[0] if isinstance(item, tuple) else item
    return DENOM_ORDER.index(d) if d in DENOM_ORDER else 99


def merge_passes(pass1: Dict[str, Dict[str, int]],
                 pass2: Dict[str, Dict[str, int]]
                 ) -> Dict[str, Dict[str, int]]:
    """Merge двух проходов: max() при дубликатах."""
    merged: Dict[str, Dict[str, int]] = {}

    for data in (pass1, pass2):
        for stype, denoms in data.items():
            if stype not in merged:
                merged[stype] = {}
            for denom, qty in denoms.items():
                merged[stype][denom] = max(
                    merged[stype].get(denom, 0), qty
                )

    return merged


# ═══════════════════════════════════════════════════
# РЕЖИМ: EXTRACT
# ═══════════════════════════════════════════════════

def mode_extract(emulator: dict, ocr: OCREngine):
    """
    Диагностический режим: сохраняет скриншот + нарезанные ячейки.

    Для каждой ячейки сохраняет:
    - cell_rX_cY.png           — полная ячейка
    - cell_rX_cY_type.png      — зона типа (иконка)
    - cell_rX_cY_denom.png     — зона номинала
    - cell_rX_cY_qty.png       — зона количества
    - cell_rX_cY_qty_ocr.png   — OCR-input (scale 5x + padding)

    Также сохраняет аннотированный скриншот с сеткой.
    """
    logger.info("=" * 60)
    logger.info("РЕЖИМ: EXTRACT — диагностика для нарезки шаблонов")
    logger.info("=" * 60)

    screenshot = get_screenshot(emulator)
    if screenshot is None:
        logger.error("❌ Не удалось получить скриншот!")
        return

    h, w = screenshot.shape[:2]
    logger.success(f"✅ Скриншот: {w}x{h}")

    ensure_debug_dir()
    ts = datetime.now().strftime('%H%M%S')

    # Полный скриншот
    full_path = DEBUG_DIR / f"{ts}_full_screenshot.png"
    cv2.imwrite(str(full_path), screenshot)
    logger.info(f"📸 Полный скриншот: {full_path}")

    # ── Аннотированный скриншот с сеткой ──
    annotated = screenshot.copy()

    cell_count = 0

    for row in range(len(GRID_ROWS)):
        for col in range(len(GRID_COLS)):
            x1, y1, x2, y2 = get_cell_bounds(col, row)

            # Проверяем границы
            if y2 > h:
                continue

            cell = screenshot[y1:y2, x1:x2]
            if cell.size == 0:
                continue

            label = f"r{row}_c{col}"
            cell_count += 1

            # ── Сохраняем полную ячейку ──
            cell_path = DEBUG_DIR / f"{ts}_{label}_cell.png"
            cv2.imwrite(str(cell_path), cell)

            # ── Зона типа (иконка) ──
            type_crop = crop_zone(cell, TYPE_ZONE)
            if type_crop.size > 0:
                cv2.imwrite(
                    str(DEBUG_DIR / f"{ts}_{label}_type.png"),
                    type_crop
                )

            # ── Зона номинала ──
            denom_crop = crop_zone(cell, DENOM_ZONE)
            if denom_crop.size > 0:
                cv2.imwrite(
                    str(DEBUG_DIR / f"{ts}_{label}_denom.png"),
                    denom_crop
                )

            # ── Зона количества ──
            qty_crop = crop_zone(cell, QTY_ZONE)
            if qty_crop.size > 0:
                cv2.imwrite(
                    str(DEBUG_DIR / f"{ts}_{label}_qty.png"),
                    qty_crop
                )
                # OCR input (для проверки)
                enlarged = cv2.resize(
                    qty_crop, None, fx=QTY_SCALE, fy=QTY_SCALE,
                    interpolation=cv2.INTER_CUBIC
                )
                padded = cv2.copyMakeBorder(
                    enlarged,
                    QTY_PADDING, QTY_PADDING,
                    QTY_PADDING, QTY_PADDING,
                    cv2.BORDER_CONSTANT, value=(0, 0, 0)
                )
                cv2.imwrite(
                    str(DEBUG_DIR / f"{ts}_{label}_qty_ocr.png"),
                    padded
                )

            # ── OCR количества (для отладки) ──
            qty_val = ocr_quantity(qty_crop, ocr, label)

            # ── Рисуем на аннотированном ──
            # Рамка ячейки
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 1)

            # Зона типа (синим)
            tx1, ty1 = x1 + TYPE_ZONE['x1'], y1 + TYPE_ZONE['y1']
            tx2, ty2 = x1 + TYPE_ZONE['x2'], y1 + TYPE_ZONE['y2']
            cv2.rectangle(annotated, (tx1, ty1), (tx2, ty2), (255, 0, 0), 1)

            # Зона номинала (жёлтым)
            dx1, dy1 = x1 + DENOM_ZONE['x1'], y1 + DENOM_ZONE['y1']
            dx2, dy2 = x1 + DENOM_ZONE['x2'], y1 + DENOM_ZONE['y2']
            cv2.rectangle(annotated, (dx1, dy1), (dx2, dy2), (0, 255, 255), 1)

            # Зона количества (красным)
            qx1, qy1 = x1 + QTY_ZONE['x1'], y1 + QTY_ZONE['y1']
            qx2, qy2 = x1 + QTY_ZONE['x2'], y1 + QTY_ZONE['y2']
            cv2.rectangle(annotated, (qx1, qy1), (qx2, qy2), (0, 0, 255), 1)

            # Подпись
            qty_text = str(qty_val) if qty_val is not None else "?"
            cv2.putText(annotated, qty_text,
                        (x1 + 5, y2 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                        (255, 255, 255), 1)

            logger.info(
                f"  [{label}] cell=({x1},{y1})-({x2},{y2}) "
                f"qty_ocr={qty_val}"
            )

    # Сохраняем аннотированный
    ann_path = DEBUG_DIR / f"{ts}_annotated.png"
    cv2.imwrite(str(ann_path), annotated)

    logger.info(f"\n📊 Нарезано {cell_count} ячеек")
    logger.info(f"📸 Аннотированный: {ann_path}")
    logger.info(f"📁 Debug: {DEBUG_DIR}")

    logger.info(
        f"\n💡 Следующие шаги:\n"
        f"   1. Откройте аннотированный скриншот и проверьте сетку\n"
        f"   2. Скорректируйте GRID_COLS, GRID_Y_START, ROW_HEIGHT\n"
        f"   3. Из *_type.png нарежьте шаблоны типов → "
        f"{TYPE_TEMPLATE_DIR}/\n"
        f"   4. Из *_denom.png нарежьте шаблоны номиналов → "
        f"{DENOM_TEMPLATE_DIR}/\n"
        f"   5. Запустите --parse для проверки"
    )


# ═══════════════════════════════════════════════════
# ПАРСИНГ ОДНОГО ЭКРАНА
# ═══════════════════════════════════════════════════

def parse_screen(screenshot: np.ndarray, ocr: OCREngine,
                 pass_num: int = 1, save_debug: bool = False
                 ) -> Dict[str, Dict[str, int]]:
    """
    Парсинг одного экрана рюкзака.

    Для каждой ячейки сетки:
    1. Template match ТИП
    2. Template match НОМИНАЛ
    3. OCR КОЛИЧЕСТВО

    Returns:
        {speedup_type: {denomination: quantity}}
    """
    h, w = screenshot.shape[:2]
    ts = datetime.now().strftime('%H%M%S') if save_debug else ""

    # Загружаем шаблоны (проверяем доступность)
    type_available = {k: v for k, v in TYPE_TEMPLATES.items() if v.exists()}
    denom_available = {k: v for k, v in DENOM_TEMPLATES.items() if v.exists()}

    if not type_available:
        logger.error(
            f"❌ Нет шаблонов типов в {TYPE_TEMPLATE_DIR}/\n"
            f"   Сначала запустите --extract и нарежьте шаблоны!"
        )
        return {}

    if not denom_available:
        logger.error(
            f"❌ Нет шаблонов номиналов в {DENOM_TEMPLATE_DIR}/\n"
            f"   Сначала запустите --extract и нарежьте шаблоны!"
        )
        return {}

    logger.info(
        f"\n{'='*60}\n"
        f"ПРОХОД {pass_num}: шаблоны типов={len(type_available)}, "
        f"номиналов={len(denom_available)}\n"
        f"{'='*60}"
    )

    result: Dict[str, Dict[str, int]] = {}
    parsed_count = 0
    empty_count = 0

    for row in range(len(GRID_ROWS)):
        for col in range(len(GRID_COLS)):
            x1, y1, x2, y2 = get_cell_bounds(col, row)

            if y2 > h:
                continue

            cell = screenshot[y1:y2, x1:x2]
            if cell.size == 0:
                continue

            label = f"r{row}_c{col}"

            # ── 1. Template match ТИП ──
            type_crop = crop_zone(cell, TYPE_ZONE)
            type_match = match_best_template(
                type_crop, type_available, THRESHOLD_TYPE
            )

            if type_match is None:
                empty_count += 1
                logger.debug(f"  [{label}] пустая ячейка (тип не определён)")
                continue

            stype, type_conf = type_match

            # ── 2. Template match НОМИНАЛ ──
            denom_crop = crop_zone(cell, DENOM_ZONE)
            denom_match = match_best_template(
                denom_crop, denom_available, THRESHOLD_DENOM
            )

            if denom_match is None:
                logger.warning(
                    f"  [{label}] тип={stype}({type_conf:.2f}), "
                    f"но номинал не определён!"
                )
                continue

            denom, denom_conf = denom_match

            # ── 3. OCR КОЛИЧЕСТВО ──
            qty_crop = crop_zone(cell, QTY_ZONE)
            qty = ocr_quantity(qty_crop, ocr, label)

            if qty is None:
                logger.warning(
                    f"  [{label}] {stype}/{denom} — "
                    f"OCR не распознал количество"
                )
                continue

            # ── Сохраняем результат ──
            if stype not in result:
                result[stype] = {}
            result[stype][denom] = qty

            parsed_count += 1
            logger.info(
                f"  [{label}] ✅ {stype}/{denom} = {qty}  "
                f"(type={type_conf:.2f}, denom={denom_conf:.2f})"
            )

            # ── Debug сохранение ──
            if save_debug:
                ensure_debug_dir()
                cv2.imwrite(
                    str(DEBUG_DIR / f"{ts}_p{pass_num}_{label}_cell.png"),
                    cell
                )

    logger.info(
        f"\n📊 Проход {pass_num}: "
        f"распознано={parsed_count}, пусто={empty_count}"
    )

    return result


# ═══════════════════════════════════════════════════
# РЕЖИМ: SINGLE PASS
# ═══════════════════════════════════════════════════

def mode_single_pass(emulator: dict, ocr: OCREngine):
    """Один проход без свайпа — для быстрой итерации."""
    logger.info("=" * 60)
    logger.info("РЕЖИМ: ОДИНОЧНЫЙ ПРОХОД (без свайпа)")
    logger.info("=" * 60)

    screenshot = get_screenshot(emulator)
    if screenshot is None:
        logger.error("❌ Не удалось получить скриншот!")
        return

    result = parse_screen(screenshot, ocr, pass_num=1, save_debug=True)
    print_result(result)


# ═══════════════════════════════════════════════════
# РЕЖИМ: FULL PARSE (два прохода)
# ═══════════════════════════════════════════════════

def mode_full_parse(emulator: dict, ocr: OCREngine):
    """Полный парсинг: 2 прохода со свайпом, merge результатов."""
    logger.info("=" * 60)
    logger.info("РЕЖИМ: ПОЛНЫЙ ПАРСИНГ (2 прохода)")
    logger.info("=" * 60)

    # ── Проход 1 ──
    screenshot1 = get_screenshot(emulator)
    if screenshot1 is None:
        logger.error("❌ Не удалось получить скриншот!")
        return

    pass1 = parse_screen(screenshot1, ocr, pass_num=1, save_debug=True)

    # ── Свайп вниз ──
    logger.info("\n📜 Свайп вниз...")
    x1, y1, x2, y2, dur = SWIPE_DOWN
    swipe(emulator, x1=x1, y1=y1, x2=x2, y2=y2, duration=dur)
    time.sleep(1.0)

    # ── Проход 2 ──
    screenshot2 = get_screenshot(emulator)
    if screenshot2 is None:
        logger.error("❌ Не удалось получить скриншот после свайпа!")
        return

    pass2 = parse_screen(screenshot2, ocr, pass_num=2, save_debug=True)

    # ── Свайп назад ──
    logger.info("\n📜 Свайп вверх (возврат)...")
    x1, y1, x2, y2, dur = SWIPE_UP
    swipe(emulator, x1=x1, y1=y1, x2=x2, y2=y2, duration=dur)

    # ── Merge ──
    merged = merge_passes(pass1, pass2)

    logger.info("\n" + "=" * 60)
    logger.info("📊 ФИНАЛЬНЫЙ РЕЗУЛЬТАТ (merged):")
    logger.info("=" * 60)
    print_result(merged)


# ═══════════════════════════════════════════════════
# ВЫВОД РЕЗУЛЬТАТА
# ═══════════════════════════════════════════════════

def print_result(result: Dict[str, Dict[str, int]]):
    """Красивый вывод результата парсинга."""
    if not result:
        logger.warning("⚠️ Пустой результат — ничего не распознано")
        return

    total_all_seconds = 0

    for stype in sorted(result.keys()):
        denoms = result[stype]
        ordered = sorted(denoms.items(), key=denom_sort_key)
        items = ', '.join(f"{d}={q}" for d, q in ordered)
        total_sec = sum(DENOM_SECONDS.get(d, 0) * q for d, q in denoms.items())
        hours = total_sec / 3600
        total_all_seconds += total_sec
        logger.info(f"  [{stype:12s}]: {items}  ({hours:.1f}ч)")

    total_hours = total_all_seconds / 3600
    logger.info(f"\n  🕐 ВСЕГО: {total_hours:.1f}ч "
                f"({total_all_seconds:,} сек)")


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Тест парсинга ускорений из Рюкзака"
    )
    parser.add_argument('--extract', action='store_true',
                        help='Диагностика: нарезка ячеек для шаблонов')
    parser.add_argument('--parse', action='store_true',
                        help='Полный парсинг (2 прохода со свайпом)')
    parser.add_argument('--single', action='store_true',
                        help='Один проход без свайпа')
    parser.add_argument('--id', type=int, default=DEFAULT_EMULATOR_ID,
                        help=f'ID эмулятора (default: {DEFAULT_EMULATOR_ID})')
    parser.add_argument('--port', type=int, default=DEFAULT_EMULATOR_PORT,
                        help=f'Порт эмулятора (default: {DEFAULT_EMULATOR_PORT})')
    args = parser.parse_args()

    if not args.extract and not args.parse and not args.single:
        args.extract = True

    emulator = get_emulator(args.id, args.port)

    logger.info("=" * 60)
    logger.info("ТЕСТ ПАРСИНГА РЮКЗАКА v1.0")
    logger.info(f"Эмулятор: ID={args.id}, порт={args.port}")
    logger.info("=" * 60)

    logger.info("\n🔧 Инициализация OCR...")
    ocr = OCREngine(lang='ru')

    if args.extract:
        mode_extract(emulator, ocr)

    if args.single:
        mode_single_pass(emulator, ocr)

    if args.parse:
        mode_full_parse(emulator, ocr)

    logger.info("\n✅ Тест завершён")


if __name__ == "__main__":
    main()