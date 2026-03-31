"""
Тест speedup_applier — парсинг позиций ускорений + свайпы

Предусловие: эмулятор ID=7 запущен, игра загружена,
окно ускорений ОТКРЫТО (любое — строительство/тренировка/эволюция).

Тесты:
  1. OCR сканирование видимых ускорений (_scan_visible_speedups)
  2. Свайп вниз + повторное сканирование
  3. Свайп к стартовой позиции + повторное сканирование
  4. Парсинг таймера из окна ускорений
  5. Парсинг алмазов (текущие)
  6. (Опционально) Одиночный клик "Использовать" на самом мелком номинале

Запуск:
  python tests/test_speedup_applier.py

  С одиночным кликом:
  python tests/test_speedup_applier.py --click
"""

import os
import sys
import time
import argparse

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import logger
from utils.ocr_engine import OCREngine
from utils.image_recognition import get_screenshot
from utils.adb_controller import tap, swipe, press_key

from functions.prime_times.speedup_applier import (
    _scan_visible_speedups,
    _parse_speedup_text,
    _parse_remaining_timer,
    _parse_current_diamonds,
    _parse_diamond_cost,
    _do_swipe_down,
    _do_swipe_to_start,
    _check_context_completion,
    _find_target_slot,
    TIMER_AREAS,
    COORD_USE_BUTTON_X,
    DIAMOND_MAX_COST,
    DENOM_SECONDS,
)
from functions.backpack_speedups.backpack_storage import BackpackStorage


# ═══════════════════════════════════════════════════
# КОНФИГУРАЦИЯ ТЕСТА
# ═══════════════════════════════════════════════════

EMULATOR = {
    'id': 7,
    'name': 'LDPlayer-7',
    'port': 5568,
}


def separator(title: str):
    """Визуальный разделитель для вывода."""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"  {title}")
    logger.info(f"{'=' * 60}\n")


# ═══════════════════════════════════════════════════
# ТЕСТ 1: OCR СКАНИРОВАНИЕ
# ═══════════════════════════════════════════════════

def test_scan_visible(ocr: OCREngine):
    """
    Сканирование видимых ускорений на текущем экране.
    Выводит все найденные слоты с координатами.
    """
    separator("ТЕСТ 1: OCR сканирование видимых ускорений")

    slots = _scan_visible_speedups(EMULATOR, ocr)

    if not slots:
        logger.warning("⚠️ Ни одного ускорения не найдено!")
        logger.info("Проверьте что окно ускорений открыто на эмуляторе")
        return []

    logger.success(f"✅ Найдено {len(slots)} ускорений:")
    for i, slot in enumerate(slots):
        sec = DENOM_SECONDS.get(slot.denomination, 0)
        logger.info(
            f"  [{i}] {slot.speedup_type:10s} / {slot.denomination:4s} "
            f"({sec // 60:>4d} мин) → кнопка ({slot.button_x}, {slot.button_y})"
        )

    return slots


# ═══════════════════════════════════════════════════
# ТЕСТ 2: СВАЙП ВНИЗ + ПОВТОРНОЕ СКАНИРОВАНИЕ
# ═══════════════════════════════════════════════════

def test_swipe_down(ocr: OCREngine):
    """Свайп вниз и повторное сканирование."""
    separator("ТЕСТ 2: Свайп вниз + сканирование")

    logger.info("⬇️ Свайп вниз...")
    _do_swipe_down(EMULATOR)
    time.sleep(0.5)

    slots = _scan_visible_speedups(EMULATOR, ocr)

    if not slots:
        logger.warning("⚠️ После свайпа ничего не найдено")
        return []

    logger.success(f"✅ После свайпа найдено {len(slots)} ускорений:")
    for i, slot in enumerate(slots):
        sec = DENOM_SECONDS.get(slot.denomination, 0)
        logger.info(
            f"  [{i}] {slot.speedup_type:10s} / {slot.denomination:4s} "
            f"({sec // 60:>4d} мин) → кнопка ({slot.button_x}, {slot.button_y})"
        )

    return slots


# ═══════════════════════════════════════════════════
# ТЕСТ 3: СВАЙП К НАЧАЛУ + ПОВТОРНОЕ СКАНИРОВАНИЕ
# ═══════════════════════════════════════════════════

def test_swipe_to_start(ocr: OCREngine):
    """Возврат к стартовой позиции и повторное сканирование."""
    separator("ТЕСТ 3: Свайп к стартовой позиции + сканирование")

    logger.info("⬆️ 2 свайпа назад к стартовой позиции...")
    _do_swipe_to_start(EMULATOR)
    time.sleep(0.5)

    slots = _scan_visible_speedups(EMULATOR, ocr)

    if not slots:
        logger.warning("⚠️ После возврата ничего не найдено")
        return []

    logger.success(f"✅ После возврата найдено {len(slots)} ускорений:")
    for i, slot in enumerate(slots):
        sec = DENOM_SECONDS.get(slot.denomination, 0)
        logger.info(
            f"  [{i}] {slot.speedup_type:10s} / {slot.denomination:4s} "
            f"({sec // 60:>4d} мин) → кнопка ({slot.button_x}, {slot.button_y})"
        )

    return slots


# ═══════════════════════════════════════════════════
# ТЕСТ 4: ПАРСИНГ ТАЙМЕРА
# ═══════════════════════════════════════════════════

def test_parse_timer(ocr: OCREngine):
    """Парсинг таймера из окна ускорений для всех контекстов."""
    separator("ТЕСТ 4: Парсинг таймера")

    for ctx in ['building', 'training', 'evolution']:
        timer = _parse_remaining_timer(EMULATOR, ocr, ctx)
        area = TIMER_AREAS.get(ctx)

        if timer is not None:
            h = timer // 3600
            m = (timer % 3600) // 60
            s = timer % 60
            logger.success(
                f"  {ctx:12s} → {timer:>7d} сек "
                f"({h:02d}:{m:02d}:{s:02d}), "
                f"область {area}"
            )
        else:
            logger.warning(
                f"  {ctx:12s} → не распознан, область {area}"
            )


# ═══════════════════════════════════════════════════
# ТЕСТ 5: ПАРСИНГ АЛМАЗОВ
# ═══════════════════════════════════════════════════

def test_parse_diamonds(ocr: OCREngine):
    """Парсинг текущего количества алмазов + стоимости на кнопке."""
    separator("ТЕСТ 5: Парсинг алмазов")

    # Сначала убедимся что мы на стартовой позиции
    # (кнопка "Завершить Сейчас" видна только сверху)
    _do_swipe_to_start(EMULATOR)
    time.sleep(0.5)

    # 5a: Текущие алмазы
    diamonds = _parse_current_diamonds(EMULATOR, ocr)
    if diamonds is not None:
        logger.success(f"  💎 Текущие алмазы: {diamonds:,}")
    else:
        logger.warning("  💎 Текущие алмазы не распознаны")

    # 5b: Стоимость на кнопке "Завершить Сейчас"
    cost = _parse_diamond_cost(EMULATOR, ocr)
    if cost is not None:
        affordable = "✅ выгодно" if cost <= DIAMOND_MAX_COST else "❌ дорого"
        enough = ""
        if diamonds is not None:
            enough = ", хватает ✅" if diamonds >= cost else ", НЕ хватает ❌"
        logger.success(
            f"  💎 Стоимость 'Завершить Сейчас': {cost} алмазов "
            f"(порог ≤{DIAMOND_MAX_COST}: {affordable}{enough})"
        )
    else:
        logger.warning("  💎 Стоимость 'Завершить Сейчас' не распознана")


# ═══════════════════════════════════════════════════
# ТЕСТ 6: RAW OCR (дамп всего что видит OCR)
# ═══════════════════════════════════════════════════

def test_raw_ocr(ocr: OCREngine):
    """
    Дамп всех OCR-элементов на экране.
    Полезно для отладки если _scan_visible_speedups не находит ускорения.
    """
    separator("ТЕСТ 6: RAW OCR дамп всех элементов")

    screenshot = get_screenshot(EMULATOR)
    if screenshot is None:
        logger.error("❌ Не удалось получить скриншот")
        return

    elements = ocr.recognize_text(screenshot, min_confidence=0.3)

    if not elements:
        logger.warning("⚠️ OCR не распознал ни одного элемента")
        return

    logger.info(f"Всего элементов: {len(elements)}\n")

    for i, el in enumerate(elements):
        text = el['text']
        x, y = el['x'], el['y']
        conf = el.get('confidence', 0)

        # Пробуем парсить как ускорение
        parsed = _parse_speedup_text(text)
        marker = ""
        if parsed:
            stype, denom = parsed
            marker = f" ✅ → {stype}/{denom}"
        elif 'ускорен' in text.lower():
            marker = " ⚠️ содержит 'ускорен' но не спарсилось"

        logger.info(
            f"  [{i:2d}] x={x:4d} y={y:4d} "
            f"conf={conf:.2f} | '{text}'{marker}"
        )


# ═══════════════════════════════════════════════════
# ТЕСТ 7: ОДИНОЧНЫЙ КЛИК (ОПЦИОНАЛЬНО)
# ═══════════════════════════════════════════════════

def test_single_click(ocr: OCREngine):
    """
    Одиночный клик "Использовать" на самом мелком номинале.

    ⚠️ РАСХОДУЕТ 1 ускорение! Использовать осторожно.
    """
    separator("ТЕСТ 7: Одиночный клик 'Использовать'")

    # Убедимся что мы на стартовой позиции
    _do_swipe_to_start(EMULATOR)
    time.sleep(0.5)

    slots = _scan_visible_speedups(EMULATOR, ocr)
    if not slots:
        logger.error("❌ Нет видимых ускорений для клика")
        return

    # Выбираем самый мелкий номинал (первый по Y, обычно 1m)
    target = slots[0]
    logger.info(
        f"🎯 Цель: {target.speedup_type}/{target.denomination} "
        f"→ кнопка ({target.button_x}, {target.button_y})"
    )

    # Проверяем quantity в БД до клика
    storage = BackpackStorage()
    emu_id = EMULATOR['id']
    qty_before = storage.get_quantity(
        emu_id, target.speedup_type, target.denomination
    )
    logger.info(f"  Quantity в БД до клика: {qty_before}")

    # Клик
    logger.info(f"  👆 Клик по ({target.button_x}, {target.button_y})...")
    tap(EMULATOR, target.button_x, target.button_y)
    time.sleep(1.0)

    # Обновляем БД
    new_qty = storage.use_speedup(
        emu_id, target.speedup_type, target.denomination
    )
    logger.info(f"  Quantity в БД после клика: {new_qty}")

    # Пересканируем
    time.sleep(0.5)
    slots_after = _scan_visible_speedups(EMULATOR, ocr)
    logger.success(
        f"✅ Клик выполнен. Видимых ускорений: "
        f"{len(slots)} → {len(slots_after)}"
    )

    # Проверяем маркеры завершения (не должны появиться от 1 клика)
    for ctx in ['building', 'training', 'evolution']:
        completed = _check_context_completion(EMULATOR, ctx)
        if completed:
            logger.warning(
                f"⚠️ Маркер завершения ({ctx}) обнаружен! "
                f"Улучшение завершилось"
            )


# ═══════════════════════════════════════════════════
# ТЕСТ 8: СРАВНЕНИЕ БД С ЭКРАНОМ
# ═══════════════════════════════════════════════════

def test_db_vs_screen(ocr: OCREngine):
    """
    Сравнить данные из speedup_inventory с тем что видно на экране.
    Полезно для проверки актуальности БД.
    """
    separator("ТЕСТ 8: Сравнение БД с экраном")

    storage = BackpackStorage()
    emu_id = EMULATOR['id']

    if not storage.has_data(emu_id):
        logger.warning("⚠️ Нет данных в БД для этого эмулятора")
        logger.info("Сначала запустите парсинг рюкзака (backpack_speedups)")
        return

    inventory = storage.get_inventory(emu_id)

    logger.info("📦 Данные из БД (speedup_inventory):")
    for stype in sorted(inventory.keys()):
        denoms = inventory[stype]
        parts = [f"{d}×{q}" for d, q in sorted(denoms.items())]
        logger.info(f"  {stype:12s}: {', '.join(parts)}")

    # Сканируем экран
    _do_swipe_to_start(EMULATOR)
    time.sleep(0.5)

    all_screen_slots = []

    # Стартовая позиция
    slots = _scan_visible_speedups(EMULATOR, ocr)
    all_screen_slots.extend(slots)

    # Свайп 1
    _do_swipe_down(EMULATOR)
    slots = _scan_visible_speedups(EMULATOR, ocr)
    for s in slots:
        key = (s.speedup_type, s.denomination)
        if not any((x.speedup_type, x.denomination) == key for x in all_screen_slots):
            all_screen_slots.append(s)

    # Свайп 2
    _do_swipe_down(EMULATOR)
    slots = _scan_visible_speedups(EMULATOR, ocr)
    for s in slots:
        key = (s.speedup_type, s.denomination)
        if not any((x.speedup_type, x.denomination) == key for x in all_screen_slots):
            all_screen_slots.append(s)

    # Возврат
    _do_swipe_to_start(EMULATOR)

    logger.info(f"\n📱 На экране найдено {len(all_screen_slots)} уникальных номиналов:")
    for s in all_screen_slots:
        in_db = s.denomination in inventory.get(s.speedup_type, {})
        marker = "✅" if in_db else "❌ НЕТ В БД"
        logger.info(
            f"  {s.speedup_type:12s} / {s.denomination:4s} {marker}"
        )


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Тест speedup_applier на эмуляторе"
    )
    parser.add_argument(
        '--click', action='store_true',
        help="Выполнить одиночный клик 'Использовать' (расходует 1 ускорение!)"
    )
    parser.add_argument(
        '--raw', action='store_true',
        help="Вывести RAW OCR дамп всех элементов"
    )
    parser.add_argument(
        '--db', action='store_true',
        help="Сравнить БД с экраном"
    )
    parser.add_argument(
        '--only', type=int, default=None,
        help="Запустить только конкретный тест (1-8)"
    )
    args = parser.parse_args()

    logger.info("🧪 Тест speedup_applier")
    logger.info(f"   Эмулятор: {EMULATOR['name']} (id={EMULATOR['id']}, port={EMULATOR['port']})")
    logger.info(f"   ⚠️  Убедитесь что окно ускорений ОТКРЫТО на эмуляторе!\n")

    ocr = OCREngine(lang='ru')

    if args.only:
        # Запуск конкретного теста
        tests = {
            1: lambda: test_scan_visible(ocr),
            2: lambda: test_swipe_down(ocr),
            3: lambda: test_swipe_to_start(ocr),
            4: lambda: test_parse_timer(ocr),
            5: lambda: test_parse_diamonds(ocr),
            6: lambda: test_raw_ocr(ocr),
            7: lambda: test_single_click(ocr),
            8: lambda: test_db_vs_screen(ocr),
        }
        test_fn = tests.get(args.only)
        if test_fn:
            test_fn()
        else:
            logger.error(f"❌ Тест #{args.only} не существует (доступны 1-8)")
        return

    # Последовательный запуск
    test_scan_visible(ocr)

    input("\n⏸ Нажмите Enter для теста свайпа вниз...")
    test_swipe_down(ocr)

    input("\n⏸ Нажмите Enter для теста возврата к началу...")
    test_swipe_to_start(ocr)

    test_parse_timer(ocr)
    test_parse_diamonds(ocr)

    if args.raw:
        test_raw_ocr(ocr)

    if args.db:
        test_db_vs_screen(ocr)

    if args.click:
        confirm = input(
            "\n⚠️  Тест с кликом расходует 1 ускорение! "
            "Продолжить? (y/n): "
        )
        if confirm.strip().lower() == 'y':
            test_single_click(ocr)
        else:
            logger.info("Клик отменён")

    separator("ТЕСТЫ ЗАВЕРШЕНЫ")


if __name__ == '__main__':
    main()