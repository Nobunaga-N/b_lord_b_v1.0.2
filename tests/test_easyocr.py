"""
Тест EasyOCR на реальном эмуляторе

Сравнивает с PaddleOCR по скорости и точности
"""

import time
from utils.ocr_engine_easyocr import get_ocr_engine_easyocr
from utils.ocr_engine import get_ocr_engine
from utils.image_recognition import get_screenshot
from utils.logger import logger


def test_easyocr():
    print("\n" + "=" * 70)
    print("🧪 ТЕСТ: EasyOCR vs PaddleOCR")
    print("=" * 70 + "\n")

    # Эмулятор
    emulator = {'id': 1, 'name': 'Test', 'port': 5556}

    # Скриншот
    print("📸 Получение скриншота...")
    screenshot = get_screenshot(emulator)

    if screenshot is None:
        print("❌ Ошибка получения скриншота!")
        return

    print(f"✅ Скриншот: {screenshot.shape[1]}x{screenshot.shape[0]}\n")

    # ===== ТЕСТ 1: EasyOCR =====
    print("=" * 70)
    print("⚡ ТЕСТ 1: EasyOCR (GPU)")
    print("=" * 70 + "\n")

    try:
        ocr_easy = get_ocr_engine_easyocr()
        ocr_easy.set_debug_mode(True)

        print("Парсинг панели навигации...")
        start = time.time()
        buildings_easy = ocr_easy.parse_navigation_panel(screenshot, emulator['id'])
        time_easy = time.time() - start

        print(f"✅ Распознано: {len(buildings_easy)} зданий")
        print(f"⏱️  Время: {time_easy:.2f} сек\n")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        buildings_easy = []
        time_easy = 0

    # ===== ТЕСТ 2: PaddleOCR =====
    print("=" * 70)
    print("🐢 ТЕСТ 2: PaddleOCR (CPU)")
    print("=" * 70 + "\n")

    try:
        ocr_paddle = get_ocr_engine()
        ocr_paddle.set_debug_mode(False)

        print("Парсинг панели навигации...")
        start = time.time()
        buildings_paddle = ocr_paddle.parse_navigation_panel(screenshot, emulator['id'])
        time_paddle = time.time() - start

        print(f"✅ Распознано: {len(buildings_paddle)} зданий")
        print(f"⏱️  Время: {time_paddle:.2f} сек\n")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        buildings_paddle = []
        time_paddle = 0

    # ===== СРАВНЕНИЕ =====
    print("=" * 70)
    print("📊 СРАВНЕНИЕ")
    print("=" * 70 + "\n")

    speedup = time_paddle / time_easy if time_easy > 0 else 0

    print("┌" + "─" * 25 + "┬" + "─" * 12 + "┬" + "─" * 12 + "┬" + "─" * 12 + "┐")
    print("│ Движок                  │ Время (сек) │ Зданий     │ Ускорение  │")
    print("├" + "─" * 25 + "┼" + "─" * 12 + "┼" + "─" * 12 + "┼" + "─" * 12 + "┤")
    print(f"│ {'EasyOCR (GPU)':<23} │ {time_easy:>10.2f} │ {len(buildings_easy):>10} │ {speedup:>9.2f}x │")
    print(f"│ {'PaddleOCR (CPU)':<23} │ {time_paddle:>10.2f} │ {len(buildings_paddle):>10} │ {'1.00x':>11} │")
    print("└" + "─" * 25 + "┴" + "─" * 12 + "┴" + "─" * 12 + "┴" + "─" * 12 + "┘")

    if speedup > 1:
        print(f"\n🚀 EasyOCR быстрее на {speedup:.1f}x!")

    # Детали
    if buildings_easy:
        print("\n📋 Детали (EasyOCR):\n")
        for i, b in enumerate(buildings_easy[:5], 1):
            print(f"  {i}. {b['name']} (Lv.{b['level']}) #{b['index']}")

    print("\n✅ Тест завершён!")
    print(f"📁 Debug: data/screenshots/debug/ocr/emu1_navigation_*.png\n")


if __name__ == "__main__":
    try:
        test_easyocr()
    except KeyboardInterrupt:
        print("\n⏸️ Прервано")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        logger.exception(e)