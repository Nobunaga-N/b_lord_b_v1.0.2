"""
Детальный вывод того, что ONNX реально распознает
"""

from utils.ocr_engine_onnx import get_ocr_engine_onnx
from utils.image_recognition import get_screenshot
from utils.logger import logger


def test_onnx_raw():
    print("\n" + "=" * 70)
    print("🔍 ДЕТАЛЬНЫЙ ВЫВОД ONNX OCR")
    print("=" * 70 + "\n")

    # Эмулятор
    emulator = {'id': 1, 'name': 'Test', 'port': 5556}

    # Скриншот
    print("📸 Получение скриншота...")
    screenshot = get_screenshot(emulator)

    if screenshot is None:
        print("❌ Ошибка!\n")
        return

    print(f"✅ Скриншот: {screenshot.shape[1]}x{screenshot.shape[0]}\n")

    # Инициализация OCR
    print("🔍 Инициализация ONNX OCR...")
    ocr = get_ocr_engine_onnx()
    ocr.set_debug_mode(True)
    print()

    # ===== 1. RAW распознавание (без парсинга) =====
    print("=" * 70)
    print("📝 RAW РАСПОЗНАВАНИЕ (что видит ONNX)")
    print("=" * 70 + "\n")

    elements = ocr.recognize_text(screenshot, min_confidence=0.5)

    if not elements:
        print("❌ Ничего не распознано!\n")
        return

    print(f"Распознано элементов: {len(elements)}\n")

    for i, elem in enumerate(elements, 1):
        print(f"{i:2}. '{elem['text']:<30}' (conf: {elem['confidence']:.2f}, y: {elem['y']:3})")

    # ===== 2. Группировка по строкам =====
    print("\n" + "=" * 70)
    print("📋 ГРУППИРОВКА ПО СТРОКАМ")
    print("=" * 70 + "\n")

    rows = ocr.group_by_rows(elements, y_threshold=20)

    print(f"Строк: {len(rows)}\n")

    for i, row in enumerate(rows, 1):
        full_text = ' '.join([elem['text'] for elem in row])
        y_coord = int(sum([elem['y'] for elem in row]) / len(row))
        print(f"{i:2}. (y={y_coord:3}) '{full_text}'")

    # ===== 3. Парсинг уровней =====
    print("\n" + "=" * 70)
    print("🔍 ПАРСИНГ УРОВНЕЙ")
    print("=" * 70 + "\n")

    for i, row in enumerate(rows, 1):
        full_text = ' '.join([elem['text'] for elem in row])

        level = ocr.parse_level(full_text)
        building_name = ocr.parse_building_name(full_text)

        print(f"Строка {i}:")
        print(f"  Raw:  '{full_text}'")
        print(f"  Name: '{building_name}'")
        print(f"  Level: {level}")

        if level is not None and len(building_name) >= 3:
            print(f"  ✅ РАСПОЗНАНО!")
        else:
            print(f"  ❌ Отфильтровано (level={level}, len(name)={len(building_name)})")
        print()

    # ===== 4. Финальный результат parse_navigation_panel =====
    print("=" * 70)
    print("🏗️ ФИНАЛЬНЫЙ РЕЗУЛЬТАТ (parse_navigation_panel)")
    print("=" * 70 + "\n")

    buildings = ocr.parse_navigation_panel(screenshot, emulator['id'])

    if buildings:
        print(f"✅ Распознано зданий: {len(buildings)}\n")
        for b in buildings:
            print(f"  • {b['name']} Lv.{b['level']} (#{b['index']})")
    else:
        print("❌ Здания не распознаны!\n")

    print("\n" + "=" * 70)
    print("✅ ТЕСТ ЗАВЕРШЁН")
    print("=" * 70 + "\n")

    # Подсказка
    print("📁 Проверь debug скриншот:")
    print("   data/screenshots/debug/ocr/emu1_navigation_*.png")
    print("   Там видно что OCR распознал (bbox с текстом)\n")


if __name__ == "__main__":
    try:
        test_onnx_raw()
    except KeyboardInterrupt:
        print("\n⏸️ Прервано")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        logger.exception(e)