"""
Тестовый скрипт для ds_navigator.py

Запускать из корня проекта:
  python tests/test_ds_navigator.py

Предусловие:
  - Эмулятор запущен, игра открыта
  - Бот находится в поместье (главный экран)

Тесты:
  1. parse_points_value()       — юнит-тест конвертации очков (без эмулятора)
  2. Полный цикл parse_ds_points() — навигация + OCR (на живом эмуляторе)
  3. OCR отдельных областей     — скриншот + парсинг без навигации
  4. Пошаговая навигация        — каждый шаг с подтверждением

Использование:
  python tests/test_ds_navigator.py              — все тесты
  python tests/test_ds_navigator.py unit         — только юнит-тесты
  python tests/test_ds_navigator.py navigate     — только навигация
  python tests/test_ds_navigator.py screenshot   — только OCR со скриншота
  python tests/test_ds_navigator.py step         — пошаговая навигация

ID / PORT эмулятора настраиваются ниже.
"""

import os
import sys
import time
import cv2

# Добавляем корень проекта в sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from utils.logger import logger
from utils.ocr_engine import OCREngine
from utils.image_recognition import get_screenshot
from utils.adb_controller import tap, press_key

from functions.prime_times.ds_navigator import (
    parse_ds_points,
    parse_points_value,
    _ocr_area,
    _open_event_center,
    _find_and_open_ds,
    _parse_points_from_screen,
    AREA_CURRENT_POINTS,
    AREA_SHELL_1,
    AREA_SHELL_2,
    DELAY_AFTER_ESC,
)

# ═══════════════════════════════════════════════════
# НАСТРОЙКИ ТЕСТОВОГО ЭМУЛЯТОРА
# ═══════════════════════════════════════════════════

EMULATOR = {
    'id': 7,
    'name': 'LDPlayer-7',
    'port': 5568,
}

# Папка для дебаг-скриншотов
DEBUG_DIR = os.path.join(ROOT_DIR, 'data', 'screenshots', 'debug')


# ═══════════════════════════════════════════════════
# УТИЛИТА: Рисование областей на скриншоте
# ═══════════════════════════════════════════════════

def save_debug_screenshot_with_areas(screenshot, filename="ds_areas_debug.png"):
    """
    Сохранить скриншот с нарисованными прямоугольниками
    областей парсинга очков ДС.
    """
    os.makedirs(DEBUG_DIR, exist_ok=True)

    debug_img = screenshot.copy()

    areas = {
        'CURRENT_POINTS': (AREA_CURRENT_POINTS, (0, 255, 0)),    # зелёный
        'SHELL_1':        (AREA_SHELL_1, (0, 255, 255)),          # жёлтый
        'SHELL_2':        (AREA_SHELL_2, (0, 165, 255)),          # оранжевый
    }

    for label, (area, color) in areas.items():
        x1, y1, x2, y2 = area

        # Прямоугольник
        cv2.rectangle(debug_img, (x1, y1), (x2, y2), color, 2)

        # Подпись
        text = f"{label} ({x1},{y1})-({x2},{y2})"
        text_y = y1 - 8 if y1 > 25 else y2 + 18
        cv2.putText(
            debug_img, text, (x1, text_y),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1
        )

    filepath = os.path.join(DEBUG_DIR, filename)
    cv2.imwrite(filepath, debug_img)
    logger.info(f"📸 Дебаг-скриншот с областями: {filepath}")
    return filepath


# ═══════════════════════════════════════════════════
# ТЕСТ 1: Юнит-тесты parse_points_value (без эмулятора)
# ═══════════════════════════════════════════════════

def test_parse_points_value():
    """Проверка конвертации текстовых форматов очков."""
    logger.info("=" * 60)
    logger.info("ТЕСТ 1: parse_points_value() — юнит-тесты")
    logger.info("=" * 60)

    test_cases = [
        # (входная строка, ожидаемый результат)
        ("0", 0),
        ("999", 999),
        ("1500", 1500),
        ("1.5K", 1500),
        ("118.45K", 118450),
        ("270K", 270000),
        ("90.00K", 90000),
        ("690.00K", 690000),
        ("3.20M", 3200000),
        ("1M", 1000000),
        ("0.5M", 500000),
        ("4.79M", 4790000),
        # Кириллические варианты (OCR может выдать)
        ("118.45К", 118450),
        ("3.20М", 3200000),
        # С пробелами/запятыми
        (" 1.5K ", 1500),
        ("1,5K", 1500),
        # Невалидные
        ("", None),
        ("abc", None),
        ("K", None),
        # Десятичные без суффикса (OCR не распознал K/M)
        ("90.00", None),
        ("690.00", None),
    ]

    passed = 0
    failed = 0

    for text, expected in test_cases:
        result = parse_points_value(text)
        status = "✅" if result == expected else "❌"

        if result == expected:
            passed += 1
        else:
            failed += 1

        logger.info(
            f"  {status} parse_points_value('{text}') "
            f"= {result} (ожидалось {expected})"
        )

    logger.info(f"\nИтого: {passed} passed, {failed} failed")
    return failed == 0


# ═══════════════════════════════════════════════════
# ТЕСТ 2: Полный цикл навигации (живой эмулятор)
# ═══════════════════════════════════════════════════

def test_full_navigation():
    """
    Полный цикл: поместье → Центр Событий → ДС → парсинг → возврат.

    ПРЕДУСЛОВИЕ: эмулятор в поместье!
    """
    logger.info("=" * 60)
    logger.info("ТЕСТ 2: Полный цикл parse_ds_points()")
    logger.info("=" * 60)

    logger.info(f"Эмулятор: {EMULATOR['name']} (id={EMULATOR['id']}, port={EMULATOR['port']})")
    logger.info("Предусловие: бот в поместье")

    input("\n>>> Нажми Enter когда бот в поместье...")

    ocr = OCREngine(lang='ru')

    result = parse_ds_points(EMULATOR, ocr)

    if result is None:
        logger.error("❌ parse_ds_points вернул None — навигация или OCR не удались")
        return False

    logger.success(f"✅ Результат:")
    logger.info(f"  Текущие очки: {result['current']}")
    logger.info(f"  Ракушка 1:    {result['shell_1']}")
    logger.info(f"  Ракушка 2:    {result['shell_2']}")

    # Валидация
    ok = True

    if result['shell_1'] <= 0:
        logger.warning("⚠️ shell_1 <= 0 — подозрительно")
        ok = False

    if result['shell_2'] <= result['shell_1']:
        logger.warning("⚠️ shell_2 <= shell_1 — подозрительно")
        ok = False

    if result['current'] < 0:
        logger.warning("⚠️ current < 0 — подозрительно")
        ok = False

    if ok:
        # Расчёт примерного target_minutes
        from functions.prime_times.speedup_calculator import calculate_target_minutes

        ppm = 400  # стандарт
        target_shell2 = calculate_target_minutes(
            result['current'], result['shell_2'], ppm
        )
        target_shell1 = calculate_target_minutes(
            result['current'], result['shell_1'], ppm
        )

        logger.info(f"\n  📊 При {ppm} очков/мин:")
        logger.info(f"    До ракушки 1: {target_shell1} мин ({target_shell1 / 60:.1f}ч)")
        logger.info(f"    До ракушки 2: {target_shell2} мин ({target_shell2 / 60:.1f}ч)")

    return ok


# ═══════════════════════════════════════════════════
# ТЕСТ 3: OCR со скриншота (без навигации)
# ═══════════════════════════════════════════════════

def test_ocr_from_screenshot():
    """
    Парсинг очков из текущего экрана БЕЗ навигации.

    Полезно когда ты вручную открыл окно ДС и хочешь
    проверить только OCR-парсинг областей.

    ПРЕДУСЛОВИЕ: экран с ДС уже открыт!
    """
    logger.info("=" * 60)
    logger.info("ТЕСТ 3: OCR парсинг со скриншота")
    logger.info("=" * 60)

    logger.info(f"Эмулятор: {EMULATOR['name']}")
    logger.info("Предусловие: окно ДС (Действия Стаи) уже открыто")

    input("\n>>> Нажми Enter когда окно ДС открыто на экране...")

    ocr = OCREngine(lang='ru')

    # Скриншот
    screenshot = get_screenshot(EMULATOR)
    if screenshot is None:
        logger.error("❌ Не удалось получить скриншот")
        return False

    # Сохраняем скриншот с прямоугольниками областей
    save_debug_screenshot_with_areas(
        screenshot,
        f"ds_areas_{EMULATOR['id']}.png"
    )

    # Сохраняем кропы каждой области
    areas = {
        'current_points': AREA_CURRENT_POINTS,
        'shell_1': AREA_SHELL_1,
        'shell_2': AREA_SHELL_2,
    }

    os.makedirs(DEBUG_DIR, exist_ok=True)

    for name, (x1, y1, x2, y2) in areas.items():
        crop = screenshot[y1:y2, x1:x2]
        crop_path = os.path.join(DEBUG_DIR, f"ds_{name}_{EMULATOR['id']}.png")
        cv2.imwrite(crop_path, crop)

        # Увеличенная версия (как в _ocr_area)
        scale = 3
        enlarged = cv2.resize(
            crop, None, fx=scale, fy=scale,
            interpolation=cv2.INTER_CUBIC
        )
        padding = 15
        padded = cv2.copyMakeBorder(
            enlarged, padding, padding, padding, padding,
            cv2.BORDER_CONSTANT, value=(0, 0, 0)
        )
        enlarged_path = os.path.join(
            DEBUG_DIR, f"ds_{name}_enlarged_{EMULATOR['id']}.png"
        )
        cv2.imwrite(enlarged_path, padded)

        logger.info(f"  📸 {name}: кроп={crop_path}")
        logger.info(f"  📸 {name}: enlarged={enlarged_path}")

    # Парсим
    logger.info("\n--- OCR результаты ---")

    results = {}
    for name, area in areas.items():
        value = _ocr_area(screenshot, area, ocr, name)
        results[name] = value
        status = "✅" if value is not None else "❌"
        logger.info(f"  {status} {name}: {value}")

    # Полный парсинг через _parse_points_from_screen
    logger.info("\n--- Полный парсинг ---")
    full_result = _parse_points_from_screen(EMULATOR, ocr)

    if full_result:
        logger.success(f"  ✅ current={full_result['current']}, "
                       f"shell_1={full_result['shell_1']}, "
                       f"shell_2={full_result['shell_2']}")
    else:
        logger.error("  ❌ _parse_points_from_screen вернул None")

    return full_result is not None


# ═══════════════════════════════════════════════════
# ТЕСТ 4: Пошаговая навигация (для отладки)
# ═══════════════════════════════════════════════════

def test_step_by_step():
    """
    Пошаговая навигация с паузами для отладки.

    Каждый шаг — отдельное действие с подтверждением.
    """
    logger.info("=" * 60)
    logger.info("ТЕСТ 4: Пошаговая навигация")
    logger.info("=" * 60)

    # Шаг 1: Открыть Центр Событий
    input("\n>>> [Шаг 1] Нажми Enter чтобы открыть Центр Событий...")
    ok = _open_event_center(EMULATOR)
    logger.info(f"  _open_event_center: {'✅' if ok else '❌'}")
    if not ok:
        return False

    # Шаг 2: Найти ДС
    input("\n>>> [Шаг 2] Нажми Enter чтобы найти ДС в списке...")
    ok = _find_and_open_ds(EMULATOR)
    logger.info(f"  _find_and_open_ds: {'✅' if ok else '❌'}")
    if not ok:
        press_key(EMULATOR, "ESC")
        time.sleep(DELAY_AFTER_ESC)
        return False

    # Шаг 3: Скриншот с областями
    input("\n>>> [Шаг 3] Нажми Enter чтобы сделать скриншот с областями...")
    screenshot = get_screenshot(EMULATOR)
    if screenshot is not None:
        save_debug_screenshot_with_areas(
            screenshot,
            f"ds_step_areas_{EMULATOR['id']}.png"
        )

    # Шаг 4: Парсинг
    input("\n>>> [Шаг 4] Нажми Enter чтобы спарсить очки...")
    ocr = OCREngine(lang='ru')
    points = _parse_points_from_screen(EMULATOR, ocr)

    if points:
        logger.success(
            f"  ✅ current={points['current']}, "
            f"shell_1={points['shell_1']}, "
            f"shell_2={points['shell_2']}"
        )
    else:
        logger.error("  ❌ Парсинг не удался")

    # Шаг 5: Выход
    input("\n>>> [Шаг 5] Нажми Enter чтобы выйти (2×ESC)...")
    press_key(EMULATOR, "ESC")
    time.sleep(DELAY_AFTER_ESC)
    press_key(EMULATOR, "ESC")
    time.sleep(DELAY_AFTER_ESC)

    logger.info("  Выход выполнен")
    return points is not None


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

    logger.info(f"🧪 Тест ds_navigator.py — режим: {mode}")
    logger.info(f"📂 Корень проекта: {ROOT_DIR}")
    logger.info("")

    if mode == 'unit':
        test_parse_points_value()

    elif mode == 'navigate':
        test_full_navigation()

    elif mode == 'screenshot':
        test_ocr_from_screenshot()

    elif mode == 'step':
        test_step_by_step()

    elif mode == 'all':
        logger.info("🔧 Запуск всех тестов\n")

        # Юнит-тесты (без эмулятора)
        test_parse_points_value()

        # С эмулятором
        ans = input(
            "\n>>> Запустить тесты на живом эмуляторе? (y/n): "
        ).strip().lower()

        if ans == 'y':
            test_full_navigation()

    else:
        logger.error(
            f"Неизвестный режим: {mode}\n"
            f"Доступные: unit, navigate, screenshot, step, all"
        )


if __name__ == '__main__':
    main()