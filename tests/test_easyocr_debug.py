"""
Детальная диагностика EasyOCR

Показывает:
- Использует ли GPU
- Что именно распознано (raw текст)
- Почему не парсятся здания
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


if __name__ == "__main__":
    try:
        test_easyocr_debug()
    except KeyboardInterrupt:
        print("\n⏸️ Прервано")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        logger.exception(e)