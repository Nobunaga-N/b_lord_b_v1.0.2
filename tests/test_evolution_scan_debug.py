"""
Тест: дебаг OCR-сканирования раздела "Развитие Территории"
+ fallback через увеличенный кроп для непривязанных названий

Цель: понять почему "Резвый Подъем" пропускается на swipe_group 1
и проверить fallback-механизм через 5x увеличение.

Эмулятор: emulator-5564, id=5
"""

import os
import sys
import re
import time

# Добавляем корень проекта в sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import cv2
import numpy as np

from utils.adb_controller import swipe, press_key
from utils.image_recognition import get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger
from functions.research.evolution_upgrade import EvolutionUpgrade


# ===== КОНФИГУРАЦИЯ =====
EMULATOR = {
    'id': 5,
    'name': 'test beast 18 lvl',
    'adb_device': 'emulator-5564',
    'port': 5564,
}

SECTION_NAME = "Развитие Территории"

SWIPE_CONFIG = {
    'swipe_1': [270, 821, 270, 81],
    'swipe_2': [270, 849, 270, 95],
}

# Какую swipe_group дебажим (0, 1, 2 или 'all')
TARGET_GROUP = 'all'

# Мусорные названия, которые не являются технологиями
NOISE_NAMES = {
    "развитиетерритории",
    "эволюцияделаетвашутерриториюещесильнее",
    "эволюцияделаетвашутерриториюещесильнее.",
}

# Паттерны для уровней (дублируем из EvolutionUpgrade)
LEVEL_PATTERN = re.compile(r'(\d+)\s*/\s*(\d+)')
MAX_PATTERN = re.compile(r'[MМ][AА][XХ]', re.IGNORECASE)


def is_noise_name(text: str) -> bool:
    """Проверить, является ли текст мусорным (заголовок, подпись и т.п.)."""
    cleaned = re.sub(r'[^\w]', '', text, flags=re.UNICODE).lower()
    return cleaned in NOISE_NAMES


def dump_raw_ocr(ocr: OCREngine, screenshot, label: str):
    """Вывести ВСЕ сырые OCR-элементы без фильтрации."""
    elements = ocr.recognize_text(screenshot, min_confidence=0.3)

    logger.info(f"\n{'='*60}")
    logger.info(f"📋 СЫРОЙ OCR — {label}")
    logger.info(f"{'='*60}")
    logger.info(f"Всего элементов: {len(elements)}")

    for i, elem in enumerate(elements):
        text = elem.get('text', '')
        x = elem.get('x', '?')
        y = elem.get('y', '?')
        conf = elem.get('confidence', '?')
        x_min = elem.get('x_min', '?')
        y_min = elem.get('y_min', '?')
        x_max = elem.get('x_max', '?')
        y_max = elem.get('y_max', '?')

        marker = ""
        if re.search(r'[Рр]езв|[Пп]одъ[её]м|[Пп]одь', text, re.IGNORECASE):
            marker = " ⭐ ЦЕЛЕВОЙ"

        logger.info(
            f"  [{i:2d}] text='{text}' | "
            f"x={x}, y={y} | "
            f"bbox=({x_min},{y_min})-({x_max},{y_max}) | "
            f"conf={conf}{marker}"
        )

    return elements


def dump_merged(upgrade: EvolutionUpgrade, elements: list, label: str):
    """Вывести результат склейки _merge_multiline_elements."""
    merged = upgrade._merge_multiline_elements(elements)

    logger.info(f"\n{'='*60}")
    logger.info(f"🔗 ПОСЛЕ СКЛЕЙКИ — {label}")
    logger.info(f"{'='*60}")
    logger.info(f"Всего элементов: {len(merged)}")

    for i, elem in enumerate(merged):
        text = elem.get('text', '')
        x = elem.get('x', '?')
        y = elem.get('y', '?')
        is_merged = elem.get('merged', False)

        marker = ""
        if re.search(r'[Рр]езв|[Пп]одъ[её]м|[Пп]одь', text, re.IGNORECASE):
            marker = " ⭐ ЦЕЛЕВОЙ"

        tag = " [СКЛЕЕНО]" if is_merged else ""

        logger.info(
            f"  [{i:2d}] text='{text}' | x={x}, y={y}{tag}{marker}"
        )

    return merged


def try_fallback_for_name(ocr: OCREngine, screenshot, name: dict, label: str):
    """
    Fallback: найти уровень для непривязанного названия
    через увеличенный кроп области ВЫШЕ названия.

    Регион: (name_x - 70, name_y - 90) → (name_x + 70, name_y - 20)
    Увеличение: 5x
    """
    name_text = name['text']
    name_x = name['x']
    name_y = name['y']

    # Область выше названия, где должен быть уровень
    x1 = max(0, name_x - 70)
    y1 = max(0, name_y - 90)
    x2 = min(screenshot.shape[1], name_x + 70)
    y2 = max(0, name_y - 20)

    if y2 <= y1:
        logger.warning(f"    ⚠️ Некорректный регион для '{name_text}': y2={y2} <= y1={y1}")
        return None

    crop = screenshot[y1:y2, x1:x2]
    h, w = crop.shape[:2]

    if h < 5 or w < 5:
        logger.warning(f"    ⚠️ Слишком маленький кроп для '{name_text}': {w}x{h}")
        return None

    # Увеличиваем 5x
    enlarged = cv2.resize(crop, (w * 5, h * 5), interpolation=cv2.INTER_CUBIC)

    # Сохраняем для дебага
    debug_dir = os.path.join(BASE_DIR, 'data', 'screenshots', 'debug')
    os.makedirs(debug_dir, exist_ok=True)

    safe_name = re.sub(r'[^\w]', '_', name_text)[:30]
    crop_path = os.path.join(debug_dir, f'fallback_{safe_name}_crop.png')
    enlarged_path = os.path.join(debug_dir, f'fallback_{safe_name}_5x.png')
    cv2.imwrite(crop_path, crop)
    cv2.imwrite(enlarged_path, enlarged)

    logger.info(f"    📸 Кроп: {crop_path}")
    logger.info(f"    📸 Увеличенный (5x): {enlarged_path}")

    # OCR по увеличенному кропу
    results = ocr.recognize_text(enlarged, min_confidence=0.3)

    logger.info(f"    🔍 OCR (5x кроп): {len(results)} элементов")
    for elem in results:
        logger.info(
            f"      text='{elem.get('text', '')}' | "
            f"conf={elem.get('confidence', '?')}"
        )

    # Ищем уровень
    for elem in results:
        text = elem.get('text', '').strip()

        if MAX_PATTERN.search(text):
            logger.info(f"    ✅ FALLBACK: '{name_text}' → MAX")
            return {'current': -1, 'max': -1}

        match = LEVEL_PATTERN.search(text)
        if match:
            current = int(match.group(1))
            max_lvl = int(match.group(2))
            logger.info(f"    ✅ FALLBACK: '{name_text}' → {current}/{max_lvl}")
            return {'current': current, 'max': max_lvl}

    logger.warning(f"    ❌ FALLBACK: '{name_text}' — уровень не найден даже с 5x")
    return None


def scan_with_fallback(upgrade: EvolutionUpgrade, ocr: OCREngine,
                       screenshot, label: str):
    """
    Полный пайплайн scan_tech_levels + fallback для непривязанных.

    Возвращает список результатов (как scan_tech_levels).
    """
    # === Основной пайплайн (копия логики scan_tech_levels) ===
    elements = ocr.recognize_text(screenshot, min_confidence=0.3)
    if not elements:
        return []

    merged_elements = upgrade._merge_multiline_elements(elements)

    levels = []
    names = []

    for elem in merged_elements:
        text = elem['text'].strip()
        y = elem.get('y', 0)
        x = elem.get('x', 0)

        if MAX_PATTERN.search(text):
            levels.append({'current': -1, 'max': -1, 'y': y, 'x': x})
            continue

        match = LEVEL_PATTERN.search(text)
        if match:
            current = int(match.group(1))
            max_lvl = int(match.group(2))
            levels.append({'current': current, 'max': max_lvl, 'y': y, 'x': x})
            continue

        cleaned = ocr.normalize_cyrillic_text(text)
        if len(cleaned) >= 3 and not cleaned.isdigit():
            names.append({'text': cleaned, 'y': y, 'x': x})

    # === Основная привязка ===
    results = []
    used_names = set()

    for lvl in sorted(levels, key=lambda l: l['y']):
        best_name = None
        best_dist = 999

        for i, name in enumerate(names):
            if i in used_names:
                continue
            y_diff = name['y'] - lvl['y']
            if 5 < y_diff < 80:
                x_diff = abs(name['x'] - lvl['x'])
                if x_diff > 120:
                    continue
                dist = y_diff + x_diff * 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_name = (i, name)

        if best_name:
            idx, name = best_name
            used_names.add(idx)
            results.append({
                'name': name['text'],
                'current_level': lvl['current'],
                'max_level': lvl['max'],
                'y': lvl['y'],
            })

    # === Fallback для непривязанных ===
    unmatched = [
        names[i] for i in range(len(names))
        if i not in used_names and not is_noise_name(names[i]['text'])
    ]

    if unmatched:
        logger.info(f"\n{'='*60}")
        logger.info(f"🔄 FALLBACK ДЛЯ НЕПРИВЯЗАННЫХ — {label}")
        logger.info(f"{'='*60}")
        logger.info(f"Непривязанных (без мусора): {len(unmatched)}")

        for name in unmatched:
            logger.info(f"  🔎 Пробую fallback для: '{name['text']}' (x={name['x']}, y={name['y']})")

            level_info = try_fallback_for_name(ocr, screenshot, name, label)

            if level_info:
                results.append({
                    'name': name['text'],
                    'current_level': level_info['current'],
                    'max_level': level_info['max'],
                    'y': name['y'],
                    'fallback': True,
                })
    else:
        logger.info(f"\n  ✅ Все названия привязаны, fallback не нужен — {label}")

    return results


def scan_group(upgrade: EvolutionUpgrade, ocr: OCREngine, group: int):
    """Сканировать одну swipe_group с полным дампом."""
    label = f"swipe_group={group}"

    screenshot = get_screenshot(EMULATOR)
    if screenshot is None:
        logger.error(f"❌ Не удалось получить скриншот для {label}")
        return

    # 1. Сырой OCR
    raw_elements = dump_raw_ocr(ocr, screenshot, label)

    # 2. Склейка
    merged = dump_merged(upgrade, raw_elements, label)

    # 3. Основной пайплайн + fallback
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 ОСНОВНОЙ ПАЙПЛАЙН + FALLBACK — {label}")
    logger.info(f"{'='*60}")

    results = scan_with_fallback(upgrade, ocr, screenshot, label)

    # Итог
    logger.info(f"\n{'='*60}")
    logger.info(f"📋 ИТОГО — {label}")
    logger.info(f"{'='*60}")
    logger.info(f"Всего технологий: {len(results)}")

    for r in results:
        val = "MAX" if r['current_level'] == -1 else f"{r['current_level']}/{r['max_level']}"
        fb = " [FALLBACK]" if r.get('fallback') else ""
        logger.info(f"  📍 {r['name']}: {val}{fb}")


def main():
    logger.info("🧪 Тест: OCR-сканирование + fallback")
    logger.info(f"   Эмулятор: {EMULATOR['name']} ({EMULATOR['adb_device']})")
    logger.info(f"   Целевая группа: {TARGET_GROUP}")

    ocr = OCREngine()
    upgrade = EvolutionUpgrade()

    # Открываем окно Эволюции
    logger.info("\n📂 Открываю окно Эволюции...")
    if not upgrade.open_evolution_window(EMULATOR):
        logger.error("❌ Не удалось открыть окно Эволюции")
        return

    # Переходим в раздел
    logger.info(f"\n📂 Перехожу в раздел: {SECTION_NAME}")
    if not upgrade.navigate_to_section(EMULATOR, SECTION_NAME):
        logger.error(f"❌ Не удалось открыть раздел: {SECTION_NAME}")
        upgrade._close_evolution(EMULATOR)
        return

    groups_to_scan = [0, 1, 2] if TARGET_GROUP == 'all' else [TARGET_GROUP]

    for group in groups_to_scan:
        if group > 0:
            swipe_key = f'swipe_{group}'
            if swipe_key in SWIPE_CONFIG:
                coords = SWIPE_CONFIG[swipe_key]
                logger.info(f"\n📜 Свайп {group}: ({coords[0]},{coords[1]}) → ({coords[2]},{coords[3]})")
                swipe(EMULATOR, coords[0], coords[1], coords[2], coords[3],
                      duration=1200)
                time.sleep(2.5)

        scan_group(upgrade, ocr, group)

    # Закрываем
    logger.info("\n🔚 Закрываю окно Эволюции...")
    upgrade._close_evolution(EMULATOR)

    logger.info("\n✅ Тест завершён!")


if __name__ == '__main__':
    main()