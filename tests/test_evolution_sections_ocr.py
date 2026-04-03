"""
Тест OCR-навигации по разделам Эволюции

Проверяет новую логику matching (3 стратегии):
  1. Позиционная — Походный Отряд I / III по Y-координате
  2. По ключевому слову — Эволюция Всеядных/Травоядных/Плотоядных
  3. Стандартная — exact / containment / fuzzy

Использование:
    python tests/test_evolution_sections_ocr.py

Эмулятор: ID=5, port=5564
Старт: окно разделов эволюции УЖЕ открыто
"""

import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.adb_controller import wait_for_adb
from utils.image_recognition import get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger

EMULATOR = {
    'id': 5,
    'name': '5) test_emulator',
    'device': 'emulator-5564',
    'port': 5564,
}

ALL_SECTIONS = [
    "Быстрое Производство",
    "Развитие Территории",
    "Базовый Бой",
    "Средний Бой",
    "Походный Отряд I",
    "Особый Отряд",
    "Лечение Зверей",
    "Обучение Зверей",
    "Поход Войска II",
    "Походный Отряд III",
    "Эволюция Травоядных",
    "Эволюция Плотоядных",
    "Эволюция Всеядных",
    "Развитие Района",
    "Битва Районов",
    "Продвинутый",
]

OPTIONAL_SECTIONS = {"Поход Войска II", "Походный Отряд III"}

# ═══════════════════════════ MATCHING LOGIC (копия из evolution_upgrade) ═══

ROMAN_POSITION_SECTIONS = {
    "Походный Отряд I":   {"base": "походныйотряд", "position": 0},
    "Походный Отряд III": {"base": "походныйотряд", "position": 1},
}

PARTIAL_MATCH_KEYWORDS = {
    "Эволюция Всеядных":   "всеядных",
    "Эволюция Травоядных": "травоядных",
    "Эволюция Плотоядных": "плотоядных",
}

JUNK_PATTERNS = [
    re.compile(r'^\d+%$'),
    re.compile(r'^\d+\s*/\s*\d+$'),
    re.compile(r'^[MМ][AА][XХ]$', re.IGNORECASE),
    re.compile(r'^[\*★☆✫✯⭐✰\s\.·•●○◆◇■□▪▫\+]+$'),
    re.compile(r'Флора|Уровень|Рекомендация', re.IGNORECASE),
    re.compile(r'^[Хх×X]$'),
]


def is_junk(text: str) -> bool:
    txt = text.strip()
    if not txt or txt.isdigit():
        return True
    return any(p.match(txt) for p in JUNK_PATTERNS)


def clean(text: str) -> str:
    c = re.sub(r'[^\w\s]', '', text, flags=re.UNICODE)
    return c.replace('_', '').lower().replace(' ', '')


def merge_multiline(elements, y_thr=30, x_thr=80):
    roman_re = re.compile(r'^[IVXivx]{1,4}$')
    filtered = [e for e in elements
                if not is_junk(e['text'].strip())
                and (len(e['text'].strip()) >= 2 or roman_re.match(e['text'].strip()))]
    filtered.sort(key=lambda e: (e['y'], e['x']))

    merged, used = [], set()
    for i, a in enumerate(filtered):
        if i in used:
            continue
        group = [a]
        used.add(i)
        for j, b in enumerate(filtered):
            if j in used:
                continue
            if abs(a['x'] - b['x']) > x_thr:
                continue
            if 5 < b['y'] - a['y'] < y_thr:
                group.append(b)
                used.add(j)
                break
        if len(group) == 1:
            merged.append(group[0])
        else:
            group.sort(key=lambda e: e['y'])
            merged.append({
                'text': ' '.join(g['text'].strip() for g in group),
                'x': sum(g['x'] for g in group) // len(group),
                'y': group[0]['y'],
                '_from': [g['text'].strip() for g in group],
            })
    return merged


# ═══════════════════════════ ТРИ СТРАТЕГИИ ═══════════════════

def find_section(merged, section_name):
    """Новая логика: 3 стратегии"""

    # Стратегия 1: Позиционная (римские цифры)
    if section_name in ROMAN_POSITION_SECTIONS:
        cfg = ROMAN_POSITION_SECTIONS[section_name]
        base, pos = cfg['base'], cfg['position']
        candidates = [e for e in merged if clean(e['text']).startswith(base)]
        candidates.sort(key=lambda e: e['y'])
        if pos < len(candidates):
            return {'found': True, 'ocr': candidates[pos]['text'].strip(),
                    'strategy': 'position', 'x': candidates[pos]['x'],
                    'y': candidates[pos]['y']}
        return {'found': False, 'ocr': '', 'strategy': 'position', 'x': 0, 'y': 0}

    # Стратегия 2: Ключевое слово
    if section_name in PARTIAL_MATCH_KEYWORDS:
        kw = PARTIAL_MATCH_KEYWORDS[section_name].lower()
        for e in merged:
            if kw in e['text'].strip().lower():
                return {'found': True, 'ocr': e['text'].strip(),
                        'strategy': 'keyword', 'x': e['x'], 'y': e['y']}
        # fallthrough → стандартный

    # Стратегия 3: Стандартный matching
    target = clean(section_name)
    best, best_r = None, 0.0

    for e in merged:
        t = clean(e['text'].strip())
        if target == t:
            return {'found': True, 'ocr': e['text'].strip(),
                    'strategy': 'exact', 'x': e['x'], 'y': e['y']}
        if target in t or t in target:
            r = min(len(target), len(t)) / max(len(target), len(t)) if t else 0
            if r > best_r and r > 0.5:
                best, best_r = e, r
        if len(target) > 4 and len(t) > 4:
            common = sum(1 for a, b in zip(target, t) if a == b)
            r = common / max(len(target), len(t))
            if r > best_r and r > 0.7:
                best, best_r = e, r

    if best:
        return {'found': True, 'ocr': best['text'].strip(),
                'strategy': f'fuzzy({best_r:.2f})', 'x': best['x'], 'y': best['y']}

    return {'found': False, 'ocr': '', 'strategy': 'none', 'x': 0, 'y': 0}


# ═══════════════════════════ MAIN ════════════════════════════

def main():
    if not wait_for_adb(EMULATOR['port'], timeout=30):
        logger.error("❌ ADB не готов")
        return

    screenshot = get_screenshot(EMULATOR)
    if screenshot is None:
        logger.error("❌ Не удалось получить скриншот")
        return

    ocr = OCREngine()
    elements = ocr.recognize_text(screenshot, min_confidence=0.3)
    merged = merge_multiline(elements)

    logger.info(f"📊 OCR: {len(elements)} сырых → {len(merged)} merged")
    for i, e in enumerate(merged):
        fr = e.get('_from')
        line = f"  [{i:2d}] '{e['text']}'  ({e['x']}, {e['y']})"
        if fr:
            line += f"  ← {fr}"
        logger.info(line)

    logger.info("\n" + "=" * 65)
    logger.info("📋 MATCHING (3 стратегии):")
    logger.info("=" * 65)

    ok, fail = 0, []
    for s in ALL_SECTIONS:
        r = find_section(merged, s)
        opt = " (opt)" if s in OPTIONAL_SECTIONS else ""
        if r['found']:
            ok += 1
            logger.info(
                f"  ✅ {s}{opt}  →  '{r['ocr']}'  "
                f"[{r['strategy']}]  ({r['x']}, {r['y']})"
            )
        else:
            if s not in OPTIONAL_SECTIONS:
                fail.append(s)
            logger.warning(f"  ❌ {s}{opt}  →  НЕ НАЙДЕН  [{r['strategy']}]")

    logger.info("=" * 65)
    logger.info(f"📊 Итого: {ok}/{len(ALL_SECTIONS)}")

    # Проверка что I и III указывают на РАЗНЫЕ элементы
    r1 = find_section(merged, "Походный Отряд I")
    r3 = find_section(merged, "Походный Отряд III")
    if r1['found'] and r3['found']:
        same = (r1['x'] == r3['x'] and r1['y'] == r3['y'])
        if same:
            logger.error("🚨 BUG: Отряд I и III указывают на ОДИН элемент!")
        else:
            logger.success(
                f"✅ Отряд I ({r1['x']},{r1['y']}) ≠ "
                f"Отряд III ({r3['x']},{r3['y']})"
            )

    if fail:
        logger.error(f"🚨 Пропущены обязательные: {fail}")
    else:
        logger.success("✅ Все обязательные разделы найдены!")


if __name__ == '__main__':
    main()