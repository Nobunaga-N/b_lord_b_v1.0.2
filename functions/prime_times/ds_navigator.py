"""
Навигация в Центр Событий + парсинг очков ДС

Навигация (из поместья):
  1. Клик (506, 305) — открыть Центр Событий
  2. Верификация: шаблон event_center.png
  3. Поиск шаблона ds_event_icon.png (до 2 свайпов)
  4. Клик → верификация заголовка "Действия Стаи"
  5. OCR парсинг трёх областей (текущие очки, 1-я и 2-я ракушки)
  6. 2×ESC → возврат в поместье

Формат очков:
  "0" → 0, "999" → 999, "118.45K" → 118450, "3.20M" → 3200000

ВАЖНО: OCREngine.normalize_text() конвертирует латинские K→К, M→М
  в кириллицу. _clean_points_text() должна учитывать оба алфавита.

Зависимости: ADB, OCR, image_recognition.

Версия: 1.2 — фикс кириллических К/М после normalize_text()
"""

import os
import re
import time
import cv2
from typing import Optional, Dict, Tuple

from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger

# ═══════════════════════════════════════════════════
# ПУТИ К ШАБЛОНАМ
# ═══════════════════════════════════════════════════

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
TEMPLATE_DIR = os.path.join(
    BASE_DIR, 'data', 'templates', 'prime_times'
)

TEMPLATES = {
    'event_center': os.path.join(TEMPLATE_DIR, 'event_center.png'),
    'ds_event_icon': os.path.join(TEMPLATE_DIR, 'ds_event_icon.png'),
    'ds_header': os.path.join(TEMPLATE_DIR, 'ds_header.png'),
}

# ═══════════════════════════════════════════════════
# КООРДИНАТЫ (540×960, 240 DPI)
# ═══════════════════════════════════════════════════

# Кнопка "Центр Событий" из поместья
COORD_EVENT_CENTER = (506, 305)

# Свайп внутри Центра Событий (поиск ДС)
EVENT_SWIPE_DOWN = {
    'x1': 250, 'y1': 840, 'x2': 250, 'y2': 100, 'duration': 700
}

# Области OCR парсинга очков ДС (x1, y1, x2, y2)
AREA_CURRENT_POINTS = (365, 275, 500, 314)
AREA_SHELL_1 = (137, 444, 230, 474)
AREA_SHELL_2 = (286, 444, 390, 474)

# ═══════════════════════════════════════════════════
# ПОРОГИ И ТАЙМИНГИ
# ═══════════════════════════════════════════════════

THRESHOLD_TEMPLATE = 0.80
MAX_EVENT_SWIPES = 2

DELAY_AFTER_TAP = 1.5
DELAY_AFTER_SWIPE = 1.0
DELAY_AFTER_ESC = 0.5


# ═══════════════════════════════════════════════════
# ПУБЛИЧНЫЙ API
# ═══════════════════════════════════════════════════

def parse_ds_points(
    emulator: Dict,
    ocr: Optional[OCREngine] = None
) -> Optional[Dict]:
    """
    Навигация в Центр Событий + парсинг очков ДС.

    Полный цикл:
    1. Из поместья → Центр Событий
    2. Найти и открыть ДС
    3. Спарсить 3 значения
    4. 2×ESC → возврат в поместье

    Args:
        emulator: dict эмулятора (id, name, port)
        ocr: OCREngine (создаётся если None)

    Returns:
        {
            'current': 0,
            'shell_1': 270000,
            'shell_2': 540000,
        }
        или None при ошибке навигации
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    if ocr is None:
        ocr = OCREngine(lang='ru')

    # ── Шаг 1: Открыть Центр Событий ──
    if not _open_event_center(emulator):
        return None

    # ── Шаг 2: Найти и открыть ДС ──
    if not _find_and_open_ds(emulator):
        press_key(emulator, "ESC")
        time.sleep(DELAY_AFTER_ESC)
        return None

    # ── Шаг 3: Парсинг очков ──
    points = _parse_points_from_screen(emulator, ocr)

    # ── Шаг 4: Выход (2×ESC) ──
    press_key(emulator, "ESC")
    time.sleep(DELAY_AFTER_ESC)
    press_key(emulator, "ESC")
    time.sleep(DELAY_AFTER_ESC)

    if points is None:
        logger.warning(f"[{emu_name}] ⚠️ Не удалось спарсить очки ДС")
        return None

    logger.info(
        f"[{emu_name}] 📊 ДС очки: текущие={points['current']}, "
        f"ракушка1={points['shell_1']}, ракушка2={points['shell_2']}"
    )

    return points


def parse_points_value(text: str) -> Optional[int]:
    """
    Конвертация текстового формата очков в число.

    Форматы:
        "0"        → 0
        "999"      → 999
        "1.5K"     → 1500
        "118.45K"  → 118450
        "3.20M"    → 3200000

    Args:
        text: строка из OCR

    Returns:
        int или None если не распознано
    """
    if not text:
        return None

    text = text.strip().replace(' ', '').replace(',', '.')

    # Суффикс M (миллионы)
    match = re.match(r'^(\d+(?:\.\d+)?)M$', text, re.IGNORECASE)
    if match:
        value = float(match.group(1)) * 1_000_000
        return int(value)

    # Суффикс K (тысячи)
    match = re.match(r'^(\d+(?:\.\d+)?)K$', text, re.IGNORECASE)
    if match:
        value = float(match.group(1)) * 1_000
        return int(value)

    # Целое число (без суффикса)
    match = re.match(r'^(\d+)$', text)
    if match:
        return int(match.group(1))

    # Десятичное без суффикса — OCR не распознал K/M
    match = re.match(r'^(\d+\.\d+)$', text)
    if match:
        logger.warning(
            f"  parse_points_value: десятичное '{text}' без суффикса K/M"
        )
        return None

    return None


# ═══════════════════════════════════════════════════
# НАВИГАЦИЯ
# ═══════════════════════════════════════════════════

def _open_event_center(emulator: Dict) -> bool:
    """
    Открыть Центр Событий из поместья.

    Returns:
        True если центр открыт и верифицирован
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    logger.debug(f"[{emu_name}] Открытие Центра Событий...")
    tap(emulator, *COORD_EVENT_CENTER)
    time.sleep(DELAY_AFTER_TAP)

    template_path = TEMPLATES['event_center']
    if not os.path.exists(template_path):
        logger.warning(
            f"[{emu_name}] ⚠️ Шаблон event_center.png не найден, "
            f"продолжаем без верификации"
        )
        return True

    for attempt in range(3):
        result = find_image(
            emulator, template_path, threshold=THRESHOLD_TEMPLATE
        )
        if result:
            logger.debug(f"[{emu_name}] ✅ Центр Событий открыт")
            return True
        time.sleep(0.5)

    logger.error(f"[{emu_name}] ❌ Центр Событий не открылся")
    return False


def _find_and_open_ds(emulator: Dict) -> bool:
    """
    Найти иконку ДС в списке ивентов и открыть.

    Returns:
        True если ДС открыт
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
    template_path = TEMPLATES['ds_event_icon']

    if not os.path.exists(template_path):
        logger.error(
            f"[{emu_name}] ❌ Шаблон ds_event_icon.png не найден"
        )
        return False

    for swipe_count in range(MAX_EVENT_SWIPES + 1):
        if swipe_count > 0:
            logger.debug(
                f"[{emu_name}] Свайп {swipe_count}/{MAX_EVENT_SWIPES} "
                f"в Центре Событий"
            )
            s = EVENT_SWIPE_DOWN
            swipe(
                emulator,
                s['x1'], s['y1'], s['x2'], s['y2'], s['duration']
            )
            time.sleep(DELAY_AFTER_SWIPE)

        result = find_image(
            emulator, template_path, threshold=THRESHOLD_TEMPLATE
        )
        if result:
            cx, cy = result
            logger.debug(
                f"[{emu_name}] Иконка ДС найдена: ({cx}, {cy})"
            )
            tap(emulator, x=cx, y=cy)
            time.sleep(DELAY_AFTER_TAP)

            if _verify_ds_header(emulator):
                return True

            logger.warning(
                f"[{emu_name}] ⚠️ Заголовок ДС не найден после клика"
            )
            press_key(emulator, "ESC")
            time.sleep(DELAY_AFTER_ESC)
            continue

    logger.error(
        f"[{emu_name}] ❌ Иконка ДС не найдена после "
        f"{MAX_EVENT_SWIPES} свайпов"
    )
    return False


def _verify_ds_header(emulator: Dict) -> bool:
    """
    Верифицировать что открыто окно "Действия Стаи".

    Returns:
        True если заголовок найден
    """
    template_path = TEMPLATES['ds_header']

    if not os.path.exists(template_path):
        logger.warning(
            "⚠️ Шаблон ds_header.png не найден, "
            "пропускаем верификацию"
        )
        return True

    for attempt in range(3):
        result = find_image(
            emulator, template_path, threshold=THRESHOLD_TEMPLATE
        )
        if result:
            return True
        time.sleep(0.5)

    return False


# ═══════════════════════════════════════════════════
# ПАРСИНГ ОЧКОВ
# ═══════════════════════════════════════════════════

def _parse_points_from_screen(
    emulator: Dict,
    ocr: OCREngine
) -> Optional[Dict]:
    """
    OCR парсинг трёх областей очков ДС.

    Returns:
        {'current': int, 'shell_1': int, 'shell_2': int}
        или None если критичные значения не распознаны
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    screenshot = get_screenshot(emulator)
    if screenshot is None:
        logger.error(f"[{emu_name}] ❌ Не удалось получить скриншот ДС")
        return None

    current = _ocr_area(screenshot, AREA_CURRENT_POINTS, ocr, "текущие очки")
    shell_1 = _ocr_area(screenshot, AREA_SHELL_1, ocr, "ракушка 1")
    shell_2 = _ocr_area(screenshot, AREA_SHELL_2, ocr, "ракушка 2")

    if current is None:
        logger.warning(f"[{emu_name}] ⚠️ Текущие очки: OCR не распознал, берём 0")
        current = 0

    if shell_1 is None or shell_2 is None:
        logger.error(
            f"[{emu_name}] ❌ Не удалось спарсить очки ракушек: "
            f"shell_1={shell_1}, shell_2={shell_2}"
        )
        return None

    if shell_2 <= shell_1:
        logger.warning(
            f"[{emu_name}] ⚠️ shell_2 ({shell_2}) <= shell_1 ({shell_1}), "
            f"возможно перепутаны — меняем местами"
        )
        shell_1, shell_2 = min(shell_1, shell_2), max(shell_1, shell_2)

    return {
        'current': current,
        'shell_1': shell_1,
        'shell_2': shell_2,
    }


def _ocr_area(
    screenshot,
    area: Tuple[int, int, int, int],
    ocr: OCREngine,
    label: str
) -> Optional[int]:
    """
    OCR одной области экрана и конвертация в число.

    Args:
        screenshot: numpy array (BGR)
        area: (x1, y1, x2, y2)
        ocr: OCREngine
        label: имя области (для логов)

    Returns:
        int или None
    """
    x1, y1, x2, y2 = area
    crop = screenshot[y1:y2, x1:x2]

    if crop.size == 0:
        logger.warning(f"  OCR {label}: пустой кроп ({area})")
        return None

    # Увеличиваем для лучшего OCR (scale=5, padding=20 — как в backpack_parser)
    scale = 5
    enlarged = cv2.resize(
        crop, None, fx=scale, fy=scale,
        interpolation=cv2.INTER_CUBIC
    )

    padding = 20
    padded = cv2.copyMakeBorder(
        enlarged, padding, padding, padding, padding,
        cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )

    elements = ocr.recognize_text(padded, min_confidence=0.3)

    if not elements:
        logger.debug(f"  OCR {label}: ничего не распознано")
        return None

    # Склеиваем все тексты (на случай разбиения)
    full_text = ''.join(e['text'].strip() for e in elements)
    full_text = _clean_points_text(full_text)

    value = parse_points_value(full_text)

    if value is not None:
        logger.debug(f"  OCR {label}: '{full_text}' → {value}")
    else:
        logger.warning(f"  OCR {label}: '{full_text}' → не распознано")

    return value


def _clean_points_text(text: str) -> str:
    """
    Очистка текста очков от мусора OCR.

    ВАЖНО: OCREngine.normalize_text() конвертирует латинские K→К, M→М
    в кириллицу. Поэтому whitelist включает оба алфавита.

    Допустимые символы: цифры, точка, запятая, K/M (лат + кир).
    """
    # Удаляем всё кроме цифр, точки, запятой, K, M (латинские + кириллические)
    cleaned = re.sub(r'[^\d.,KkMmКкМм]', '', text)

    # Нормализуем кириллические в латинские (для parse_points_value)
    cleaned = cleaned.replace('К', 'K').replace('к', 'K')
    cleaned = cleaned.replace('М', 'M').replace('м', 'M')

    return cleaned