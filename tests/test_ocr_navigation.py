"""
Простой тест OCR для панели навигации
Один прогон + таблица результатов
"""

import sys
from pathlib import Path

# Добавить корень проекта в sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.ocr_engine import get_ocr_engine
from utils.image_recognition import get_screenshot
from utils.logger import logger


def print_separator(char="=", length=70):
    """Печатает разделитель"""
    print(char * length)


def print_section(title):
    """Печатает заголовок секции"""
    print(f"\n{title}\n" + "-" * 70)


def print_table_row(*columns, widths=None):
    """Печатает строку таблицы с заданными ширинами колонок"""
    if widths is None:
        widths = [5, 30, 10, 8, 8]

    row = ""
    for i, col in enumerate(columns):
        row += str(col).ljust(widths[i])
    print(row)


def main():
    """Главная функция теста"""

    print_separator()
    print("🧪 ТЕСТ OCR - Панель навигации")
    print_separator()

    # Эмулятор для теста
    emulator = {
        'id': 1,
        'name': 'LDPlayer-Test',
        'port': 5556
    }

    # ============================================
    # 1. Инициализация OCR
    # ============================================
    print_section("🔧 ИНИЦИАЛИЗАЦИЯ OCR")

    print("Создание OCR Engine...")
    ocr = get_ocr_engine()

    # Информация об устройстве
    device_info = ocr.get_device_info()
    print(f"\n✅ OCR инициализирован")
    print(f"   Устройство: {device_info['device']}")

    if device_info['use_gpu']:
        print(f"   🎮 GPU обнаружен!")
        print(f"   GPU Count: {device_info.get('gpu_count', 'N/A')}")
        print(f"   GPU Name: {device_info.get('gpu_name', 'N/A')}")
        print(f"   CUDA Version: {device_info.get('cuda_version', 'N/A')}")
        print(f"   cuDNN Version: {device_info.get('cudnn_version', 'N/A')}")
    else:
        print(f"   💻 Используется CPU")

    # Включить debug режим
    ocr.set_debug_mode(True)
    print("   Debug режим: ВКЛ")

    # ============================================
    # 2. Получение скриншота
    # ============================================
    print_section("📸 ПОЛУЧЕНИЕ СКРИНШОТА")

    print("Создание скриншота эмулятора...")
    screenshot = get_screenshot(emulator)

    if screenshot is None:
        print("\n❌ Не удалось получить скриншот!")
        print("\n🔍 Проверьте:")
        print("  1. Эмулятор с портом 5556 запущен?")
        print("  2. ADB подключен к эмулятору?")
        print("  3. Команда 'adb devices' показывает эмулятор?")
        return

    height, width = screenshot.shape[:2]
    print(f"✅ Скриншот получен: {width}x{height} px")

    # ============================================
    # 3. Распознавание зданий
    # ============================================
    print_section("🔍 РАСПОЗНАВАНИЕ ЗДАНИЙ")

    buildings = ocr.parse_navigation_panel(screenshot, emulator['id'])

    # ============================================
    # 4. Вывод результатов
    # ============================================
    print_section("📊 РЕЗУЛЬТАТЫ")

    if not buildings:
        print("⚠️  OCR не распознал здания!\n")
        print("🔍 Возможные причины:")
        print("  1. Панель навигации не открыта в игре")
        print("  2. Вкладка 'Список зданий' не активна")
        print("  3. Язык игры не русский")
        print("  4. Разрешение эмулятора не стандартное")
        print("\n💡 Проверьте debug скриншот:")
        print("   data/screenshots/debug/ocr/")
        return

    print(f"✅ Распознано зданий: {len(buildings)}\n")

    # Таблица зданий
    print_table_row("№", "Название", "Уровень", "Индекс", "Y-coord")
    print_separator("-")

    for i, building in enumerate(buildings, 1):
        # Обрезать длинное название
        name = building['name']
        if len(name) > 28:
            name = name[:25] + "..."

        print_table_row(
            i,
            name,
            f"Lv.{building['level']}",
            f"#{building['index']}",
            building['y_coord']
        )

    # ============================================
    # 5. Пример использования
    # ============================================
    print_section("💡 ПРИМЕР ИСПОЛЬЗОВАНИЯ")

    if buildings:
        example = buildings[0]
        print(f"Для перехода к зданию '{example['name']}':")
        print(f"  Уровень: {example['level']}")
        print(f"  Индекс: #{example['index']}")
        print(f"  Координаты кнопки: {example['button_coord']}")
        print(f"\n  Python код:")
        x, y = example['button_coord']
        print(f"  tap(emulator, {x}, {y})")

    # ============================================
    # 6. Debug скриншоты
    # ============================================
    print_section("📁 DEBUG ФАЙЛЫ")

    print("Debug скриншоты сохранены в:")
    print("  data/screenshots/debug/ocr/")
    print("\n🎨 Цветовая кодировка bbox:")
    print("   🟢 Зелёный  = отличная уверенность (>0.9)")
    print("   🟡 Жёлтый   = хорошая уверенность (>0.7)")
    print("   🔴 Красный  = низкая уверенность (<0.7)")

    # ============================================
    # Завершение
    # ============================================
    print()
    print_separator()
    print("✅ ТЕСТ ЗАВЕРШЁН")
    print_separator()


if __name__ == "__main__":
    main()