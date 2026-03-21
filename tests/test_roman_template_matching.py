"""
Тест v9.3 — Template Matching для римских цифр II / III

Шаблоны roman_II.png и roman_III.png вырезаются ВРУЧНУЮ из скриншота.
Скрипт находит позицию "Lv." через template matching внутри склеенных
OCR-элементов и ищет шаблон римской цифры в 35px слева от "Lv.".

Запуск:
  python tests/test_roman_template_matching.py --match
  python tests/test_roman_template_matching.py --extract

Эмулятор: ID=7, порт=5568 (переопределить: --id / --port)
"""

import sys
import re
import os
import cv2
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import logger
from utils.ocr_engine import OCREngine
from utils.image_recognition import get_screenshot

# ═══════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════

DEFAULT_EMULATOR_ID = 7
DEFAULT_EMULATOR_PORT = 5568

DEBUG_DIR = PROJECT_ROOT / "data" / "screenshots" / "debug" / "roman_templates"
TEMPLATE_DIR = PROJECT_ROOT / "data" / "templates" / "building"

ROMAN_TEMPLATES = {
    "II":  TEMPLATE_DIR / "roman_II.png",
    "III": TEMPLATE_DIR / "roman_III.png",
}

ROMAN_MATCH_THRESHOLD = 0.80

# Здания, у которых БЫВАЕТ римская цифра (фильтр от ложных срабатываний)
BUILDINGS_WITH_ROMAN = {
    "Центр Сбора",
    "Целебный Родник",
    "Полигон Зверей",
    "Походный Отряд",
    "Особый Отряд",
    "Поход Войска",
}


# ═══════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════

def get_emulator(emu_id: int, port: int) -> Dict:
    return {"id": emu_id, "name": f"Emulator-{emu_id}", "port": port}


def build_lv_template(screenshot: np.ndarray,
                      elements: List[Dict]) -> Optional[np.ndarray]:
    """
    Извлечь шаблон "Lv." из отдельного OCR-элемента "Lv.X".
    Кропает левые ~65% (только "Lv." без цифры), grayscale.
    """
    for elem in elements:
        text = elem['text'].strip()
        if re.match(r'^[LlЛл][vVуУyYвВ]\.?\s*\d+$', text) and \
           not re.search(r'[а-яА-ЯёЁ]', text):
            x1, y1 = elem['x_min'], elem['y_min']
            x2, y2 = elem['x_max'], elem['y_max']
            lv_width = int((x2 - x1) * 0.65)
            lv_x2 = x1 + lv_width
            crop = screenshot[y1:y2, x1:lv_x2]
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) \
                if len(crop.shape) == 3 else crop
            logger.info(f"  📐 Шаблон Lv. из '{text}' размер={gray.shape[1]}x{gray.shape[0]}")
            return gray
    return None


def find_lv_pixel_x(screenshot: np.ndarray,
                    elem: Dict,
                    lv_template: np.ndarray,
                    threshold: float = 0.6) -> Optional[int]:
    """
    Найти пиксельную X-позицию "Lv." внутри OCR-элемента через template matching.
    """
    x1, y1 = elem['x_min'], elem['y_min']
    x2, y2 = elem['x_max'], elem['y_max']
    crop = screenshot[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) \
        if len(crop.shape) == 3 else crop

    if lv_template.shape[0] > gray.shape[0] or lv_template.shape[1] > gray.shape[1]:
        return None

    result = cv2.matchTemplate(gray, lv_template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        abs_x = x1 + max_loc[0]
        logger.debug(f"    Lv. match: x={abs_x} conf={max_val:.3f}")
        return abs_x

    return None


def find_lv_element(row: List[Dict]) -> Optional[Dict]:
    """Найти OCR-элемент содержащий "Lv.X" в строке."""
    for elem in row:
        text = elem['text'].strip()
        if re.match(r'^[LlЛл][vVуУyYвВ]\.?\s*\d+$', text) and \
           not re.search(r'[а-яА-ЯёЁ]', text):
            return elem
    for elem in row:
        if re.search(r'[LlЛл][vVуУyYвВ]\.?\s*\d+', elem['text']):
            return elem
    return None


def find_name_element(row: List[Dict], lv_elem: Dict) -> Optional[Dict]:
    """
    Найти текстовый элемент с названием здания.
    Случай 1: отдельный элемент левее Lv.
    Случай 2: склеенный → сам lv_elem.
    """
    candidates = []
    for elem in row:
        if elem is lv_elem:
            continue
        if elem['x_min'] >= lv_elem['x_min']:
            continue
        if re.search(r'[а-яА-ЯёЁ]', elem['text']):
            candidates.append(elem)

    if candidates:
        return max(candidates, key=lambda e: e['x_max'])

    if re.search(r'[а-яА-ЯёЁ]', lv_elem['text']):
        return lv_elem

    return None


def extract_roman_zone(screenshot: np.ndarray,
                       name_elem: Dict,
                       lv_elem: Dict,
                       lv_template: Optional[np.ndarray] = None,
                       roman_width: int = 35,
                       padding: int = 2) -> Optional[np.ndarray]:
    """
    Вырезать зону слева от "Lv." где находится римская цифра.
    """
    h, w = screenshot.shape[:2]

    # Случай 1: РАЗДЕЛЬНЫЕ элементы
    if name_elem is not lv_elem and name_elem['x_max'] < lv_elem['x_min']:
        x2 = min(w, lv_elem['x_min'] + 2)
        x1 = max(0, x2 - roman_width)
        y1 = max(0, min(name_elem['y_min'], lv_elem['y_min']) - padding)
        y2 = min(h, max(name_elem['y_max'], lv_elem['y_max']) + padding)
        crop = screenshot[y1:y2, x1:x2]
        return crop if crop.size > 0 else None

    # Случай 2: СКЛЕЕННЫЙ → ищем Lv. через template matching
    lv_x = None
    if lv_template is not None:
        lv_x = find_lv_pixel_x(screenshot, name_elem, lv_template)

    # Fallback: пропорционально по тексту
    if lv_x is None:
        text = name_elem['text']
        lv_match = re.search(r'[LlЛл][vVуУyYвВ]', text)
        if lv_match:
            ratio = lv_match.start() / max(len(text), 1)
            elem_w = name_elem['x_max'] - name_elem['x_min']
            lv_x = name_elem['x_min'] + int(elem_w * ratio)
            logger.debug(f"    Lv. fallback: x={lv_x} (ratio={ratio:.2f})")

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


# ═══════════════════════════════════════════════════
# ШАБЛОНЫ РИМСКИХ ЦИФР
# ═══════════════════════════════════════════════════

def load_roman_templates() -> Dict[str, np.ndarray]:
    """Загрузить шаблоны римских цифр (grayscale)."""
    templates = {}
    for name, path in ROMAN_TEMPLATES.items():
        if not path.exists():
            logger.warning(f"⚠️ Шаблон не найден: {path}")
            continue
        img = cv2.imread(str(path))
        if img is None:
            logger.warning(f"⚠️ Не удалось загрузить: {path}")
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        templates[name] = gray
        logger.info(f"  ✅ Шаблон '{name}': {gray.shape[1]}x{gray.shape[0]}px")
    return templates


def match_roman_in_zone(zone_crop: np.ndarray,
                        templates: Dict[str, np.ndarray],
                        threshold: float = ROMAN_MATCH_THRESHOLD
                        ) -> Tuple[Optional[str], float]:
    """
    Найти римскую цифру в зоне через template matching.
    Возвращает лучшее совпадение выше threshold.
    """
    if zone_crop is None or zone_crop.size == 0:
        return None, 0.0

    gray = cv2.cvtColor(zone_crop, cv2.COLOR_BGR2GRAY) \
        if len(zone_crop.shape) == 3 else zone_crop

    best_name = None
    best_conf = 0.0

    for name, tmpl in templates.items():
        if tmpl.shape[0] > gray.shape[0] or tmpl.shape[1] > gray.shape[1]:
            logger.debug(f"    '{name}': шаблон больше зоны, пропуск")
            continue

        result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        logger.debug(f"    '{name}': conf={max_val:.3f}")

        if max_val > best_conf:
            best_conf = max_val
            best_name = name

    if best_conf >= threshold:
        return best_name, best_conf

    return None, best_conf


# ═══════════════════════════════════════════════════
# ФАЗА: EXTRACT
# ═══════════════════════════════════════════════════

def phase_extract(screenshot: np.ndarray, ocr: OCREngine):
    """Сохранить скриншот и OCR-диагностику для ручной нарезки шаблонов."""
    logger.info("=" * 60)
    logger.info("ФАЗА: EXTRACT — диагностика для ручной нарезки")
    logger.info("=" * 60)

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%H%M%S')

    raw_path = DEBUG_DIR / f"{timestamp}_full_screenshot.png"
    cv2.imwrite(str(raw_path), screenshot)
    logger.info(f"📸 Скриншот: {raw_path}")

    elements = ocr.recognize_text(screenshot, min_confidence=0.3)
    if not elements:
        logger.error("❌ OCR не распознал элементов")
        return

    rows = ocr.group_by_rows(elements, y_threshold=20)

    logger.info(f"\n📊 OCR элементы ({len(elements)}):")
    for i, elem in enumerate(elements):
        logger.info(
            f"  [{i:>2}] '{elem['text']:<35}' "
            f"x=[{elem['x_min']:>3}-{elem['x_max']:>3}] "
            f"y=[{elem['y_min']:>3}-{elem['y_max']:>3}] "
            f"conf={elem.get('confidence', 0):.2f}"
        )

    logger.info(f"\n📊 Здания:")
    for row_idx, row in enumerate(rows):
        row_text = ' '.join([e['text'] for e in row])
        level = ocr.parse_level(row_text)
        if level is None:
            continue
        has_button = any(
            re.search(r'[ПпPp][еeЕE][рpРP][еeЕE][йиĭІі][тtТT][иiІі]',
                       e['text'], re.IGNORECASE)
            for e in row
        )
        if not has_button:
            continue
        building_name = ocr.parse_building_name(row_text)
        if building_name:
            building_name = re.sub(r'\s+1\s*$', ' I', building_name)
            logger.info(f"  Row {row_idx}: {building_name:<30} Lv.{level}")

    logger.info(
        f"\n💡 Для создания шаблонов:\n"
        f"   1. Откройте: {raw_path}\n"
        f"   2. Вырежите 'II' и 'III' из строк Центр Сбора\n"
        f"   3. Сохраните:\n"
        f"      {TEMPLATE_DIR / 'roman_II.png'}\n"
        f"      {TEMPLATE_DIR / 'roman_III.png'}\n"
        f"   4. Запустите: --match"
    )


# ═══════════════════════════════════════════════════
# ФАЗА: MATCH
# ═══════════════════════════════════════════════════

def phase_match(screenshot: np.ndarray, ocr: OCREngine) -> List[Dict]:
    """
    Определить римские цифры через template matching.

    1. OCR → строки зданий
    2. Текстовый фикс "1"→"I", склейка "СбораI"→"Сбора I"
    3. Фильтр: template matching только для зданий из BUILDINGS_WITH_ROMAN
    4. Шаблон Lv. → точная позиция → кроп 35px слева
    5. Template matching кропа vs roman_II / roman_III
    """
    logger.info("=" * 60)
    logger.info("ФАЗА: MATCH — template matching римских цифр")
    logger.info("=" * 60)

    templates = load_roman_templates()
    if not templates:
        logger.error(
            "❌ Нет шаблонов! Создайте вручную:\n"
            f"   {TEMPLATE_DIR / 'roman_II.png'}\n"
            f"   {TEMPLATE_DIR / 'roman_III.png'}\n"
            "   Запустите --extract для скриншота"
        )
        return []

    elements = ocr.recognize_text(screenshot, min_confidence=0.3)
    if not elements:
        logger.error("❌ OCR не распознал элементов")
        return []

    rows = ocr.group_by_rows(elements, y_threshold=20)

    lv_template = build_lv_template(screenshot, elements)
    if lv_template is not None:
        logger.info(f"  📐 Шаблон Lv.: {lv_template.shape[1]}x{lv_template.shape[0]}px")
    else:
        logger.warning("  ⚠️ Шаблон Lv. не найден")

    timestamp = datetime.now().strftime('%H%M%S')
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    for row_idx, row in enumerate(rows):
        row_text = ' '.join([e['text'] for e in row])

        level = ocr.parse_level(row_text)
        if level is None:
            continue

        has_button = any(
            re.search(r'[ПпPp][еeЕE][рpРP][еeЕE][йиĭІі][тtТT][иiІі]',
                       e['text'], re.IGNORECASE)
            for e in row
        )
        if not has_button:
            continue

        building_name = ocr.parse_building_name(row_text)
        if not building_name:
            continue

        # Текстовый фикс "1" → "I"
        building_name = re.sub(r'\s+1\s*$', ' I', building_name)

        # Фикс склеенного "СбораI" → "Сбора I"
        building_name = re.sub(r'([а-яА-ЯёЁ])(I{1,4}|IV)\s*$',
                               r'\1 \2', building_name)

        # Проверяем, нужен ли template matching для этого здания
        needs_roman_check = any(
            base in building_name for base in BUILDINGS_WITH_ROMAN
        )

        # Извлекаем зону римской цифры
        lv_elem = find_lv_element(row)
        if lv_elem is None:
            results.append({'name': building_name, 'level': level,
                            'y': row[-1]['y'], 'method': 'ocr_only'})
            continue

        name_elem = find_name_element(row, lv_elem)
        crop = None
        if name_elem and needs_roman_check:
            crop = extract_roman_zone(screenshot, name_elem, lv_elem,
                                      lv_template=lv_template)

        # Сохраняем кроп для диагностики
        if crop is not None:
            safe_name = re.sub(r'[^\w]', '_', building_name)
            crop_path = DEBUG_DIR / f"{timestamp}_row{row_idx}_{safe_name}.png"
            cv2.imwrite(str(crop_path), crop)
            big = cv2.resize(crop, None, fx=4, fy=4,
                             interpolation=cv2.INTER_NEAREST)
            cv2.imwrite(str(crop_path.with_suffix('.x4.png')), big)

        # Template matching
        matched_roman = None
        match_conf = 0.0

        if crop is not None and crop.shape[1] >= 5:
            matched_roman, match_conf = match_roman_in_zone(crop, templates)

        # Применяем результат
        method = 'ocr_only'
        roman_re = re.search(r'\s+(I{1,4}|IV|V|VI{0,3})\s*$', building_name)
        ocr_roman = roman_re.group(1) if roman_re else None

        if matched_roman and match_conf >= ROMAN_MATCH_THRESHOLD:
            if ocr_roman and matched_roman != ocr_roman:
                # Коррекция: template видит другое чем OCR
                old_name = building_name
                if roman_re:
                    building_name = (building_name[:roman_re.start(1)]
                                     + matched_roman
                                     + building_name[roman_re.end(1):]).strip()
                else:
                    building_name = f"{building_name} {matched_roman}"
                logger.info(
                    f"  Row {row_idx}: 🔧 КОРРЕКЦИЯ '{old_name}' → '{building_name}' "
                    f"(tmpl={matched_roman}, conf={match_conf:.3f})"
                )
                method = 'template_corrected'
            elif not ocr_roman and matched_roman in ("II", "III", "IV"):
                # OCR не видел римскую — добавляем
                old_name = building_name
                building_name = f"{building_name} {matched_roman}"
                logger.info(
                    f"  Row {row_idx}: 📝 ДОБАВЛЕНО '{old_name}' → '{building_name}' "
                    f"(tmpl={matched_roman}, conf={match_conf:.3f})"
                )
                method = 'template_added'
            else:
                method = 'template_confirmed'

        crop_info = f"{crop.shape[1]}x{crop.shape[0]}" if crop is not None else "—"
        logger.debug(
            f"  Row {row_idx}: {building_name:<30} "
            f"ocr_roman={ocr_roman or '—':>4}  "
            f"tmpl={matched_roman or '—':>4} conf={match_conf:.3f}  "
            f"crop={crop_info}  method={method}"
        )

        results.append({
            'name': building_name,
            'level': level,
            'y': row[-1]['y'],
            'method': method,
            'match_roman': matched_roman,
            'match_conf': match_conf,
        })

    # Итоги
    logger.info(f"\n{'='*60}")
    logger.info("РЕЗУЛЬТАТ:")
    logger.info(f"{'='*60}")

    for i, r in enumerate(results):
        marker = ""
        if "Центр Сбора" in r['name'] and "Особый" not in r['name']:
            has_roman = bool(re.search(r'\s(I{1,3}|IV)\s*$', r['name']))
            marker = " ⭐" if has_roman else " ❌ (нет римской!)"

        match_info = ""
        if r.get('match_roman'):
            match_info = f"  [tmpl={r['match_roman']} conf={r['match_conf']:.3f} {r['method']}]"

        logger.info(f"  [{i+1}] {r['name']:<30} Lv.{r['level']}{marker}{match_info}")

    # Проверка Центров Сбора
    cs_names = [r['name'] for r in results
                if "Центр Сбора" in r['name'] and "Особый" not in r['name']]
    expected = {"Центр Сбора I", "Центр Сбора II", "Центр Сбора III"}
    found = set(cs_names) & expected
    missing = expected - found

    logger.info(f"\n  Центры Сбора: {sorted(cs_names)}")
    if missing:
        logger.error(f"  ❌ Не распознаны: {sorted(missing)}")
    else:
        logger.success("  ✅ ВСЕ ЦЕНТРЫ СБОРА РАСПОЗНАНЫ КОРРЕКТНО!")

    return results


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Тест template matching для римских цифр II/III"
    )
    parser.add_argument('--extract', action='store_true',
                        help='Сохранить скриншот + OCR-диагностику')
    parser.add_argument('--match', action='store_true',
                        help='Тест template matching с готовыми шаблонами')
    parser.add_argument('--id', type=int, default=DEFAULT_EMULATOR_ID,
                        help=f'ID эмулятора (по умолчанию {DEFAULT_EMULATOR_ID})')
    parser.add_argument('--port', type=int, default=DEFAULT_EMULATOR_PORT,
                        help=f'Порт эмулятора (по умолчанию {DEFAULT_EMULATOR_PORT})')
    args = parser.parse_args()

    if not args.extract and not args.match:
        args.match = True

    logger.info("=" * 60)
    logger.info("ТЕСТ v9.3: Template Matching для римских цифр")
    logger.info(f"Эмулятор: ID={args.id}, порт={args.port}")
    logger.info("=" * 60)

    emulator = get_emulator(args.id, args.port)

    logger.info("\n📸 Получаем скриншот...")
    screenshot = get_screenshot(emulator)
    if screenshot is None:
        logger.error("❌ Не удалось получить скриншот!")
        return

    logger.success(f"✅ Скриншот: {screenshot.shape[1]}x{screenshot.shape[0]}")

    logger.info("\n🔧 Инициализация OCR...")
    ocr = OCREngine(lang='ru')

    if args.extract:
        phase_extract(screenshot, ocr)

    if args.match:
        phase_match(screenshot, ocr)

    logger.info(f"\n📁 Debug: {DEBUG_DIR}")
    logger.info(f"📁 Шаблоны: {TEMPLATE_DIR}")


if __name__ == "__main__":
    main()