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
    print("🔍 ПАРСИНГ УРОВНЕЙ (тест всех паттернов)")
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
        print("⚠️  Возможные причины:")
        print("   1. Панель навигации не открыта в игре")
        print("   2. Вкладка 'Список зданий' не активна")
        print("   3. Все разделы свернуты (нет видимых зданий)")
        print("   4. Проблема с распознаванием уровней (проверь debug скриншот)")
    else:
        print(f"✅ Распознано зданий: {len(buildings)}\n")

        # Таблица результатов
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

        # ===== СТАТИСТИКА ВМЕСТО ЖЕСТКОЙ ПРОВЕРКИ =====
        print("\n🎯 СТАТИСТИКА:")

        # Подсчет по типам зданий
        building_counts = {}
        for b in buildings:
            name = b['name']
            if name not in building_counts:
                building_counts[name] = []
            building_counts[name].append(b['level'])

        print(f"   • Уникальных типов зданий: {len(building_counts)}")
        print(f"   • Всего зданий: {len(buildings)}")

        # Показать что распознано
        if building_counts:
            print("\n   📦 Распознанные здания:")
            for name, levels in sorted(building_counts.items()):
                levels_str = ', '.join(map(str, sorted(levels)))
                print(f"      - {name}: {len(levels)} шт (уровни: {levels_str})")

        # Диапазон уровней
        all_levels = [b['level'] for b in buildings]
        if all_levels:
            print(f"\n   📊 Диапазон уровней: {min(all_levels)}-{max(all_levels)}")
            print(f"   📊 Средний уровень: {sum(all_levels) / len(all_levels):.1f}")

    # Debug информация
    print("\n" + "=" * 70)
    print("📁 DEBUG СКРИНШОТ")
    print("=" * 70)
    print("\nПроверьте файл:")
    print("   data/screenshots/debug/ocr/emu1_navigation_*.png")
    print("\nНа скриншоте:")
    print("   🟢 Зеленый bbox = отличная уверенность (>0.9)")
    print("   🟡 Желтый bbox = хорошая уверенность (>0.7)")
    print("   🔴 Красный bbox = низкая уверенность (<0.7)")

    # Пример использования
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

    # Рекомендации
    print("\n" + "=" * 70)
    print("💡 РЕКОМЕНДАЦИИ")
    print("=" * 70 + "\n")

    if buildings:
        # Проверка качества распознавания
        low_conf_count = sum(1 for e in elements if e['confidence'] < 0.7)
        if low_conf_count > len(elements) * 0.3:  # Больше 30% низкого confidence
            print("⚠️  Много элементов с низкой уверенностью!")
            print("   Возможные решения:")
            print("   1. Улучшить освещение в игре")
            print("   2. Проверить разрешение экрана (должно быть 540x960)")
            print("   3. Убедиться что панель навигации четко видна")
        else:
            print("✅ Качество распознавания хорошее!")
            print(f"   {len(buildings)} зданий распознано корректно")

        # Проверка пропущенных зданий
        visible_buildings = len([r for r in rows if any(word in ' '.join([e['text'] for e in r]).lower()
                                                        for word in ['ферма', 'склад', 'улей', 'пруд', 'куст', 'жилище', 'логово', 'центр', 'лорд', 'флора'])])

        if visible_buildings > len(buildings):
            missing = visible_buildings - len(buildings)
            print(f"\n⚠️  Возможно пропущено зданий: ~{missing}")
            print("   Причина: не распознан уровень (проверь паттерны в parse_level)")
            print("\n   Нераспознанные строки (вероятно здания без уровня):")
            for i, row in enumerate(rows, 1):
                full_text = ' '.join([elem['text'] for elem in row])
                level = ocr.parse_level(full_text)
                building_name = ocr.parse_building_name(full_text)

                # Если похоже на здание но уровень не найден
                is_building_like = any(word in building_name.lower()
                                      for word in ['ферма', 'склад', 'улей', 'пруд', 'куст', 'жилище', 'логово', 'центр', 'лорд', 'флора'])

                if is_building_like and level is None and len(building_name) >= 3:
                    print(f"      Строка {i}: '{full_text}'")
    else:
        print("❌ Здания не распознаны!")
        print("\n   Что проверить:")
        print("   1. Панель навигации открыта?")
        print("   2. Вкладка 'Список зданий' активна?")
        print("   3. Есть ли видимые здания на панели?")
        print("   4. Посмотри debug скриншот - что OCR вообще видит")

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