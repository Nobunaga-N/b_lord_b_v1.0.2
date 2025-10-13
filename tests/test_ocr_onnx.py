"""
Тестовый скрипт для проверки OCREngineONNX на реальном эмуляторе

Сравнивает производительность и точность с PaddleOCR версией

Требования:
- Эмулятор с портом 5556 должен быть запущен
- Панель навигации должна быть открыта в игре
- Вкладка "Список зданий" должна быть активна
- ONNX модели должны быть скачаны (python scripts/download_onnx_models.py)
"""

import time
from utils.ocr_engine_onnx import get_ocr_engine_onnx
from utils.ocr_engine import get_ocr_engine  # Старая версия для сравнения
from utils.image_recognition import get_screenshot
from utils.logger import logger


def test_onnx_ocr():
    """
    Тестирует ONNX OCR на эмуляторе с портом 5556

    Шаги:
    1. Создает объект эмулятора
    2. Делает скриншот
    3. Тестирует ONNX версию
    4. Тестирует PaddleOCR версию (для сравнения)
    5. Выводит сравнение результатов
    """

    print("\n" + "=" * 70)
    print("🧪 ТЕСТ OCREngineONNX - Сравнение с PaddleOCR")
    print("=" * 70 + "\n")

    # ===== ШАГ 1: Создать объект эмулятора =====
    emulator = {
        'id': 1,
        'name': 'LDPlayer-Test',
        'port': 5556
    }

    logger.info(f"Тестируем эмулятор: {emulator['name']} (port: {emulator['port']})")

    # ===== ШАГ 2: Сделать скриншот =====
    print("\n📸 Создание скриншота...")
    screenshot = get_screenshot(emulator)

    if screenshot is None:
        print("❌ Не удалось получить скриншот!")
        print("\nПроверьте:")
        print("  1. Эмулятор с портом 5556 запущен?")
        print("  2. ADB подключен к эмулятору?")
        print("  3. Команда 'adb devices' показывает эмулятор?")
        return

    print(f"✅ Скриншот получен: {screenshot.shape[1]}x{screenshot.shape[0]}")

    # ===== ШАГ 3: Тестирование ONNX версии =====
    print("\n" + "=" * 70)
    print("🚀 ТЕСТ 1: OCREngineONNX (ONNX Runtime)")
    print("=" * 70 + "\n")

    try:
        # Инициализация
        print("🔍 Инициализация ONNX OCR...")
        ocr_onnx = get_ocr_engine_onnx()
        ocr_onnx.set_debug_mode(True)
        print("✅ ONNX OCR готов (debug режим включен)")
        print(f"   Провайдер: {ocr_onnx.providers[0]}\n")

        # Парсинг панели
        print("🏗️ Парсинг панели навигации (ONNX)...")
        start_time = time.time()
        buildings_onnx = ocr_onnx.parse_navigation_panel(screenshot, emulator['id'])
        elapsed_onnx = time.time() - start_time

        print(f"✅ ONNX: Распознано {len(buildings_onnx)} зданий за {elapsed_onnx:.2f} сек")

    except Exception as e:
        print(f"❌ Ошибка ONNX OCR: {e}")
        logger.exception(e)
        print("\nПроверьте:")
        print("  1. Модели скачаны? (python scripts/download_onnx_models.py)")
        print("  2. onnxruntime-gpu установлен? (pip install onnxruntime-gpu)")
        buildings_onnx = []
        elapsed_onnx = 0

    # ===== ШАГ 4: Тестирование PaddleOCR версии =====
    print("\n" + "=" * 70)
    print("📊 ТЕСТ 2: OCREngine (PaddleOCR) - для сравнения")
    print("=" * 70 + "\n")

    try:
        # Инициализация
        print("🔍 Инициализация PaddleOCR...")
        ocr_paddle = get_ocr_engine()
        ocr_paddle.set_debug_mode(False)  # Выключаем debug чтобы не дублировать
        print("✅ PaddleOCR готов\n")

        # Парсинг панели
        print("🏗️ Парсинг панели навигации (PaddleOCR)...")
        start_time = time.time()
        buildings_paddle = ocr_paddle.parse_navigation_panel(screenshot, emulator['id'])
        elapsed_paddle = time.time() - start_time

        print(f"✅ PaddleOCR: Распознано {len(buildings_paddle)} зданий за {elapsed_paddle:.2f} сек")

    except Exception as e:
        print(f"❌ Ошибка PaddleOCR: {e}")
        logger.exception(e)
        buildings_paddle = []
        elapsed_paddle = 0

    # ===== ШАГ 5: Сравнение результатов =====
    print("\n" + "=" * 70)
    print("📊 СРАВНЕНИЕ РЕЗУЛЬТАТОВ")
    print("=" * 70 + "\n")

    # Таблица производительности
    print("⏱️  ПРОИЗВОДИТЕЛЬНОСТЬ:")
    print("┌" + "─" * 25 + "┬" + "─" * 12 + "┬" + "─" * 12 + "┬" + "─" * 12 + "┐")
    print("│ Движок                  │ Время (сек) │ Зданий     │ Ускорение  │")
    print("├" + "─" * 25 + "┼" + "─" * 12 + "┼" + "─" * 12 + "┼" + "─" * 12 + "┤")

    speedup = elapsed_paddle / elapsed_onnx if elapsed_onnx > 0 else 0

    print(f"│ {'ONNX Runtime':<23} │ {elapsed_onnx:>10.2f} │ {len(buildings_onnx):>10} │ {speedup:>9.2f}x │")
    print(f"│ {'PaddleOCR':<23} │ {elapsed_paddle:>10.2f} │ {len(buildings_paddle):>10} │ {'1.00x':>11} │")
    print("└" + "─" * 25 + "┴" + "─" * 12 + "┴" + "─" * 12 + "┴" + "─" * 12 + "┘")

    if speedup > 1:
        print(f"\n🚀 ONNX Runtime быстрее на {speedup:.1f}x!")
    elif speedup < 1 and speedup > 0:
        print(f"\n⚠️  ONNX Runtime медленнее на {1 / speedup:.1f}x")

    # Таблица точности (сравнение зданий)
    print("\n🎯 ТОЧНОСТЬ РАСПОЗНАВАНИЯ:")

    if buildings_onnx and buildings_paddle:
        # Сравнить названия и уровни
        onnx_names = {(b['name'], b['level'], b['index']) for b in buildings_onnx}
        paddle_names = {(b['name'], b['level'], b['index']) for b in buildings_paddle}

        matching = onnx_names & paddle_names
        onnx_only = onnx_names - paddle_names
        paddle_only = paddle_names - onnx_names

        accuracy = len(matching) / max(len(onnx_names), len(paddle_names)) * 100 if onnx_names or paddle_names else 0

        print(f"  • Совпадений: {len(matching)}")
        print(f"  • Только ONNX: {len(onnx_only)}")
        print(f"  • Только PaddleOCR: {len(paddle_only)}")
        print(f"  • Точность совпадения: {accuracy:.1f}%")

        if onnx_only:
            print("\n  📝 Здания только в ONNX:")
            for name, level, index in onnx_only:
                print(f"     - {name} #{index} (Lv.{level})")

        if paddle_only:
            print("\n  📝 Здания только в PaddleOCR:")
            for name, level, index in paddle_only:
                print(f"     - {name} #{index} (Lv.{level})")

    # Детальные результаты ONNX
    if buildings_onnx:
        print("\n" + "=" * 70)
        print("📋 ДЕТАЛЬНЫЕ РЕЗУЛЬТАТЫ (ONNX)")
        print("=" * 70 + "\n")

        print("┌" + "─" * 4 + "┬" + "─" * 30 + "┬" + "─" * 8 + "┬" + "─" * 8 + "┬" + "─" * 20 + "┐")
        print("│ #  │ Название                     │ Уровень │ Индекс │ Кнопка 'Перейти'    │")
        print("├" + "─" * 4 + "┼" + "─" * 30 + "┼" + "─" * 8 + "┼" + "─" * 8 + "┼" + "─" * 20 + "┤")

        for i, building in enumerate(buildings_onnx, 1):
            name = building['name'][:28]
            level = building['level']
            index = building['index']
            button = building['button_coord']

            print(f"│ {i:<2} │ {name:<28} │ {level:^7} │ {index:^6} │ {button}     │")

        print("└" + "─" * 4 + "┴" + "─" * 30 + "┴" + "─" * 8 + "┴" + "─" * 8 + "┴" + "─" * 20 + "┘")

        # Статистика
        building_counts = {}
        for building in buildings_onnx:
            name = building['name']
            if name not in building_counts:
                building_counts[name] = 0
            building_counts[name] += 1

        print("\n📈 Статистика (ONNX):")
        print(f"  • Уникальных типов зданий: {len(building_counts)}")
        print(f"  • Всего зданий: {len(buildings_onnx)}")

        multiple_buildings = {name: count for name, count in building_counts.items() if count > 1}
        if multiple_buildings:
            print("\n  📦 Здания с несколькими экземплярами:")
            for name, count in sorted(multiple_buildings.items(), key=lambda x: -x[1]):
                print(f"     - {name}: {count} шт")

    # Debug информация
    print("\n" + "=" * 70)
    print("🔍 DEBUG ИНФОРМАЦИЯ")
    print("=" * 70 + "\n")

    print("📁 Debug скриншот ONNX сохранен:")
    print("   data/screenshots/debug/ocr/emu1_navigation_*.png")
    print("\n   На скриншоте:")
    print("   🟢 Зеленый bbox = отличная уверенность (>0.9)")
    print("   🟡 Желтый bbox = хорошая уверенность (>0.7)")
    print("   🔴 Красный bbox = низкая уверенность (<0.7)")

    # Пример использования
    if buildings_onnx:
        print("\n" + "=" * 70)
        print("💡 ПРИМЕР ИСПОЛЬЗОВАНИЯ")
        print("=" * 70 + "\n")

        example = buildings_onnx[0]
        print("Для перехода к первому зданию:")
        print(f"  Здание: {example['name']} #{example['index']}")
        print(f"  Уровень: {example['level']}")
        print(f"  Координаты кнопки: {example['button_coord']}")
        print(f"\n  Код:")
        print(f"  tap(emulator, {example['button_coord'][0]}, {example['button_coord'][1]})")

    print("\n" + "=" * 70)
    print("✅ ТЕСТ ЗАВЕРШЕН")
    print("=" * 70 + "\n")

    # Рекомендации
    if speedup > 1.5:
        print("🎉 ONNX Runtime показал отличную производительность!")
        print(f"   Рекомендуется использовать для масштабирования (8-10 эмуляторов)")
    elif speedup > 1:
        print("✅ ONNX Runtime быстрее, но не критично")
        print("   Можно использовать, особенно на GPU")
    else:
        print("⚠️  ONNX Runtime не показал преимущества")
        print("   Возможно GPU не используется или модели не оптимальны")


if __name__ == "__main__":
    try:
        test_onnx_ocr()
    except KeyboardInterrupt:
        print("\n\n⏸️  Тест прерван пользователем")
    except Exception as e:
        print(f"\n\n❌ ОШИБКА: {e}")
        logger.exception(e)
        print("\nПроверьте:")
        print("  1. ONNX модели скачаны? (python scripts/download_onnx_models.py)")
        print("  2. onnxruntime-gpu установлен? (pip install onnxruntime-gpu)")
        print("  3. Эмулятор запущен?")
        print("  4. ADB подключен?")