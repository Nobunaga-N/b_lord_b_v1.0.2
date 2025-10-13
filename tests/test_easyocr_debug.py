"""
Детальная диагностика EasyOCR

Показывает:
- Использует ли GPU
- Что именно распознано (raw текст)
- Почему не парсятся здания
- ПОЛНЫЙ ПАРСИНГ с debug скриншотом
"""

import time
from utils.ocr_engine_easyocr import get_ocr_engine_easyocr
from utils.image_recognition import get_screenshot
from utils.logger import logger


def test_easyocr_debug():
    print("\n" + "=" * 70)
    print("🔍 ДЕТАЛЬНАЯ ДИАГНОСТИКА EasyOCR")
    print("=" * 70 + "\n")

    # 1. Проверка GPU
    print("📊 Проверка GPU:")
    try:
        import torch
        print(f"   PyTorch: v{torch.__version__}")
        print(f"   CUDA доступен: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"   GPU: {torch.cuda.get_device_name(0)}")
        print()
    except ImportError:
        print("   ❌ PyTorch не установлен!\n")

    # 2. Эмулятор и скриншот
    emulator = {'id': 1, 'name': 'Test', 'port': 5556}

    print("📸 Получение скриншота...")
    screenshot = get_screenshot(emulator)

    if screenshot is None:
        print("❌ Ошибка!\n")
        return

    print(f"✅ Скриншот: {screenshot.shape[1]}x{screenshot.shape[0]}\n")

    # 3. Инициализация OCR
    print("🔍 Инициализация EasyOCR...")
    ocr = get_ocr_engine_easyocr()
    ocr.set_debug_mode(True)
    print()

    # 4. RAW распознавание (без парсинга)
    print("=" * 70)
    print("📝 RAW РАСПОЗНАВАНИЕ (что видит EasyOCR)")
    print("=" * 70 + "\n")

    elements = ocr.recognize_text(screenshot, min_confidence=0.5)

    if not elements:
        print("❌ Ничего не распознано!\n")
        return

    print(f"Распознано элементов: {len(elements)}\n")

    for i, elem in enumerate(elements, 1):
        print(f"{i:2}. '{elem['text']:<30}' (conf: {elem['confidence']:.2f}, y: {elem['y']:3})")

    # 5. Группировка по строкам
    print("\n" + "=" * 70)
    print("📋 ГРУППИРОВКА ПО СТРОКАМ")
    print("=" * 70 + "\n")

    rows = ocr.group_by_rows(elements, y_threshold=20)

    print(f"Строк: {len(rows)}\n")

    for i, row in enumerate(rows, 1):
        full_text = ' '.join([elem['text'] for elem in row])
        y_coord = int(sum([elem['y'] for elem in row]) / len(row))
        print(f"{i:2}. (y={y_coord:3}) '{full_text}'")

    # 6. Парсинг уровней
    print("\n" + "=" * 70)
    print("🔍 ПАРСИНГ УРОВНЕЙ (с новыми паттернами)")
    print("=" * 70 + "\n")

    for i, row in enumerate(rows, 1):
        full_text = ' '.join([elem['text'] for elem in row])
        level = ocr.parse_level(full_text)
        building_name = ocr.parse_building_name(full_text)

        # Показать детали парсинга
        if level is not None:
            print(f"✅ Строка {i}: '{building_name}' Lv.{level}")
            print(f"   Raw: '{full_text}'")
        elif len(building_name) >= 3:
            print(f"⚠️  Строка {i}: '{building_name}' (уровень не найден)")
            print(f"   Raw: '{full_text}'")
        else:
            print(f"❌ Строка {i}: level={level}, name='{building_name}' (отфильтровано)")

    # ===== 7. ПОЛНЫЙ ПАРСИНГ ПАНЕЛИ (ГЛАВНОЕ!) =====
    print("\n" + "=" * 70)
    print("🏗️ ПОЛНЫЙ ПАРСИНГ ПАНЕЛИ (parse_navigation_panel)")
    print("=" * 70 + "\n")

    print("Запуск parse_navigation_panel с debug режимом...")
    print("(Двухпроходное распознавание + debug скриншот)\n")

    # ===== ЗДЕСЬ ВЫЗЫВАЕТСЯ parse_navigation_panel =====
    buildings = ocr.parse_navigation_panel(screenshot, emulator['id'])
    # ===================================================

    print("\n" + "=" * 70)
    print("📊 РЕЗУЛЬТАТ")
    print("=" * 70 + "\n")

    if not buildings:
        print("❌ Здания не распознаны!\n")
    else:
        print(f"✅ Распознано зданий: {len(buildings)}\n")

        print("┌" + "─" * 4 + "┬" + "─" * 30 + "┬" + "─" * 8 + "┬" + "─" * 8 + "┬" + "─" * 20 + "┐")
        print("│ #  │ Название                     │ Уровень │ Индекс │ Кнопка 'Перейти'   │")
        print("├" + "─" * 4 + "┼" + "─" * 30 + "┼" + "─" * 8 + "┼" + "─" * 8 + "┼" + "─" * 20 + "┤")

        for i, b in enumerate(buildings, 1):
            name = b['name'][:28]
            level = b['level']
            index = b['index']
            button = b['button_coord']

            print(f"│ {i:<2} │ {name:<28} │ {level:^7} │ {index:^6} │ {button}      │")

        print("└" + "─" * 4 + "┴" + "─" * 30 + "┴" + "─" * 8 + "┴" + "─" * 8 + "┴" + "─" * 20 + "┘")

        # Сравнение с ожидаемым (по скриншоту)
        print("\n🎯 ПРОВЕРКА ПО СКРИНШОТУ:")
        expected = [
            ("Куст", 9),
            ("Куст", 10),
            ("Куст", 10),
            ("Куст", 10),
            ("Склад Листьев", 9)
        ]

        for i, (exp_name, exp_level) in enumerate(expected, 1):
            if i <= len(buildings):
                b = buildings[i - 1]
                if b['name'] == exp_name and b['level'] == exp_level:
                    print(f"   ✅ Здание {i}: {exp_name} Lv.{exp_level}")
                else:
                    print(f"   ❌ Здание {i}: ожидалось '{exp_name} Lv.{exp_level}', получено '{b['name']} Lv.{b['level']}'")
            else:
                print(f"   ❌ Здание {i}: ожидалось '{exp_name} Lv.{exp_level}', НЕ НАЙДЕНО")

    print("\n" + "=" * 70)
    print("📁 DEBUG СКРИНШОТ")
    print("=" * 70)
    print("\nПроверьте файл:")
    print("   data/screenshots/debug/ocr/emu1_navigation_*.png")
    print("\nНа скриншоте:")
    print("   🟢 Зеленый bbox = отличная уверенность (>0.9)")
    print("   🟡 Желтый bbox = хорошая уверенность (>0.7)")
    print("   🔴 Красный bbox = низкая уверенность (<0.7)")

    # ===== ДОБАВЛЕНО: Пример использования =====
    if buildings:
        print("\n" + "=" * 70)
        print("💡 ПРИМЕР ИСПОЛЬЗОВАНИЯ")
        print("=" * 70 + "\n")

        example = buildings[0]
        print(f"Для перехода к первому зданию:")
        print(f"  Здание: {example['name']} #{example['index']} (Lv.{example['level']})")
        print(f"  Координаты кнопки 'Перейти': {example['button_coord']}")
        print(f"\n  Код:")
        print(f"  from utils.adb_controller import tap")
        print(f"  tap(emulator, {example['button_coord'][0]}, {example['button_coord'][1]})")
        print(f"\n  Это кликнет на кнопку 'Перейти' для здания '{example['name']}'")

    print("\n" + "=" * 70)
    print("✅ ТЕСТ ЗАВЕРШЁН")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    try:
        test_easyocr_debug()
    except KeyboardInterrupt:
        print("\n⏸️ Прервано")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        logger.exception(e)