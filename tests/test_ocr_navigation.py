"""
Тестовый скрипт для проверки OCREngine на реальном эмуляторе

Требования:
- Эмулятор с портом 5556 должен быть запущен
- Панель навигации должна быть открыта в игре
- Вкладка "Список зданий" должна быть активна
"""

from utils.ocr_engine import get_ocr_engine
from utils.image_recognition import get_screenshot
from utils.logger import logger


def test_ocr_on_emulator():
    """
    Тестирует OCR на эмуляторе с портом 5556

    Шаги:
    1. Создает объект эмулятора
    2. Делает скриншот
    3. Включает debug режим OCR
    4. Парсит панель навигации
    5. Выводит результаты
    """

    print("\n" + "="*70)
    print("🧪 ТЕСТ OCREngine - Панель навигации")
    print("="*70 + "\n")

    # ===== ШАГ 1: Создать объект эмулятора =====
    emulator = {
        'id': 1,  # ID для debug файлов
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

    # ===== ШАГ 3: Получить OCR и включить debug =====
    print("\n🔍 Инициализация OCR...")
    ocr = get_ocr_engine()
    ocr.set_debug_mode(True)
    print("✅ OCR готов (debug режим включен)")

    # ===== ШАГ 4: Парсить панель навигации =====
    print("\n🏗️ Парсинг панели навигации...")
    buildings = ocr.parse_navigation_panel(
        screenshot=screenshot,
        emulator_id=emulator['id']
    )

    # ===== ШАГ 5: Вывод результатов =====
    print("\n" + "="*70)
    print("📊 РЕЗУЛЬТАТЫ")
    print("="*70 + "\n")

    if not buildings:
        print("⚠️ OCR не распознал здания!")
        print("\nВозможные причины:")
        print("  1. Панель навигации не открыта в игре")
        print("  2. Вкладка 'Список зданий' не активна")
        print("  3. Все разделы свернуты (нет видимых зданий)")
        print("\nПроверьте debug скриншот:")
        print("  data/screenshots/debug/ocr/emu1_navigation_*.png")
        return

    print(f"✅ Распознано зданий: {len(buildings)}\n")

    # Таблица результатов
    print("┌" + "─"*4 + "┬" + "─"*30 + "┬" + "─"*8 + "┬" + "─"*8 + "┬" + "─"*20 + "┐")
    print("│ #  │ Название                     │ Уровень │ Индекс │ Кнопка 'Перейти'    │")
    print("├" + "─"*4 + "┼" + "─"*30 + "┼" + "─"*8 + "┼" + "─"*8 + "┼" + "─"*20 + "┤")

    for i, building in enumerate(buildings, 1):
        name = building['name'][:28]  # Обрезать длинные названия
        level = building['level']
        index = building['index']
        button = building['button_coord']

        print(f"│ {i:<2} │ {name:<28} │ {level:^7} │ {index:^6} │ {button}     │")

    print("└" + "─"*4 + "┴" + "─"*30 + "┴" + "─"*8 + "┴" + "─"*8 + "┴" + "─"*20 + "┘")

    # ===== Статистика по зданиям =====
    print("\n📈 Статистика:")

    # Подсчет зданий по названиям
    building_counts = {}
    for building in buildings:
        name = building['name']
        if name not in building_counts:
            building_counts[name] = 0
        building_counts[name] += 1

    print(f"  • Уникальных типов зданий: {len(building_counts)}")
    print(f"  • Всего зданий: {len(buildings)}")

    # Здания с несколькими экземплярами
    multiple_buildings = {name: count for name, count in building_counts.items() if count > 1}
    if multiple_buildings:
        print("\n  📦 Здания с несколькими экземплярами:")
        for name, count in sorted(multiple_buildings.items(), key=lambda x: -x[1]):
            print(f"     - {name}: {count} шт")

    # ===== Debug информация =====
    print("\n" + "="*70)
    print("🔍 DEBUG ИНФОРМАЦИЯ")
    print("="*70 + "\n")

    print("📁 Debug скриншот сохранен:")
    print("   data/screenshots/debug/ocr/emu1_navigation_*.png")
    print("\n   На скриншоте:")
    print("   🟢 Зеленый bbox = отличная уверенность (>0.9)")
    print("   🟡 Желтый bbox = хорошая уверенность (>0.7)")
    print("   🔴 Красный bbox = низкая уверенность (<0.7)")

    # ===== Пример использования результатов =====
    print("\n" + "="*70)
    print("💡 ПРИМЕР ИСПОЛЬЗОВАНИЯ")
    print("="*70 + "\n")

    if buildings:
        example = buildings[0]
        print("Для перехода к первому зданию:")
        print(f"  Здание: {example['name']} #{example['index']}")
        print(f"  Уровень: {example['level']}")
        print(f"  Координаты кнопки: {example['button_coord']}")
        print(f"\n  Код:")
        print(f"  tap(emulator, {example['button_coord'][0]}, {example['button_coord'][1]})")

    print("\n" + "="*70)
    print("✅ ТЕСТ ЗАВЕРШЕН")
    print("="*70 + "\n")


if __name__ == "__main__":
    try:
        test_ocr_on_emulator()
    except KeyboardInterrupt:
        print("\n\n⏸️ Тест прерван пользователем")
    except Exception as e:
        print(f"\n\n❌ ОШИБКА: {e}")
        logger.exception(e)
        print("\nПроверьте:")
        print("  1. PaddleOCR установлен? (pip install paddleocr)")
        print("  2. Эмулятор запущен?")
        print("  3. ADB подключен?")