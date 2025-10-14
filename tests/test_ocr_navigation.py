"""
Тестовый скрипт для проверки OCREngine с GPU на реальном эмуляторе

Требования:
- Эмулятор с портом 5556 должен быть запущен
- Панель навигации должна быть открыта в игре
- Вкладка "Список зданий" должна быть активна
"""

import time
from utils.ocr_engine import get_ocr_engine
from utils.image_recognition import get_screenshot
from utils.logger import logger


def print_separator(char="=", length=70):
    """Печатает разделитель"""
    print("\n" + char * length)


def test_ocr_on_emulator():
    """
    Тестирует OCR на эмуляторе с GPU

    Проверяет:
    1. Инициализацию OCR с GPU
    2. Получение скриншота
    3. Парсинг панели навигации
    4. Производительность (время выполнения)
    5. Точность распознавания
    """

    print_separator()
    print("🧪 ТЕСТ OCREngine - GPU версия")
    print_separator()

    # ===== ШАГ 1: Информация о системе =====
    print("\n📊 ИНФОРМАЦИЯ О СИСТЕМЕ")
    print_separator("-")

    # Эмулятор для теста
    emulator = {
        'id': 1,
        'name': 'LDPlayer-Test',
        'port': 5556
    }

    logger.info(f"Эмулятор: {emulator['name']} (port: {emulator['port']})")

    # ===== ШАГ 2: Инициализация OCR =====
    print("\n🔧 ИНИЦИАЛИЗАЦИЯ OCR")
    print_separator("-")

    print("Создание OCR Engine...")
    ocr = get_ocr_engine()

    # Получить информацию об устройстве
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

    # ===== ШАГ 3: Получение скриншота =====
    print("\n📸 ПОЛУЧЕНИЕ СКРИНШОТА")
    print_separator("-")

    print("Создание скриншота эмулятора...")
    screenshot = get_screenshot(emulator)

    if screenshot is None:
        print("\n❌ Не удалось получить скриншот!")
        print("\n🔍 Проверьте:")
        print("  1. Эмулятор с портом 5556 запущен?")
        print("  2. ADB подключен к эмулятору?")
        print("  3. Команда 'adb devices' показывает эмулятор?")
        return False

    print(f"✅ Скриншот получен: {screenshot.shape[1]}x{screenshot.shape[0]} px")

    # ===== ШАГ 4: Бенчмарк производительности =====
    print("\n⚡ БЕНЧМАРК ПРОИЗВОДИТЕЛЬНОСТИ")
    print_separator("-")

    # Прогрев (первый запуск может быть медленнее)
    print("Прогрев GPU...")
    _ = ocr.parse_navigation_panel(screenshot, emulator['id'])
    print("✅ Прогрев завершён")

    # Основной тест (3 прогона)
    times = []
    num_runs = 3

    print(f"\nВыполнение {num_runs} тестовых прогонов...")

    for i in range(num_runs):
        start_time = time.time()
        buildings = ocr.parse_navigation_panel(screenshot, emulator['id'])
        elapsed = time.time() - start_time
        times.append(elapsed)
        print(f"  Прогон {i+1}: {elapsed*1000:.2f} мс ({len(buildings)} зданий)")

    # Статистика
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)

    print(f"\n📈 СТАТИСТИКА:")
    print(f"   Среднее время: {avg_time*1000:.2f} мс")
    print(f"   Минимальное:   {min_time*1000:.2f} мс")
    print(f"   Максимальное:  {max_time*1000:.2f} мс")

    # Сравнение с CPU baseline
    cpu_baseline = 2500  # ~2.5 секунды на CPU
    speedup = cpu_baseline / (avg_time * 1000)

    if device_info['use_gpu']:
        print(f"\n🚀 Ускорение vs CPU: {speedup:.1f}x")
        if speedup >= 4.0:
            print("   🏆 ОТЛИЧНО! GPU работает на полную!")
        elif speedup >= 2.0:
            print("   ✅ ХОРОШО! GPU ускоряет работу")
        else:
            print("   ⚠️  GPU медленнее ожидаемого, проверьте настройки")

    # ===== ШАГ 5: Результаты распознавания =====
    print("\n📊 РЕЗУЛЬТАТЫ РАСПОЗНАВАНИЯ")
    print_separator("-")

    if not buildings:
        print("⚠️  OCR не распознал здания!")
        print("\n🔍 Возможные причины:")
        print("  1. Панель навигации не открыта в игре")
        print("  2. Вкладка 'Список зданий' не активна")
        print("  3. Язык игры не русский")
        print("  4. Разрешение эмулятора не 540x960")
        return False

    print(f"✅ Распознано зданий: {len(buildings)}")
    print(f"\n{'№':<4} {'Название':<25} {'Уровень':<8} {'Индекс':<7} {'Y-coord':<8}")
    print("-" * 70)

    for i, building in enumerate(buildings[:15], 1):  # Показать первые 15
        name = building['name'][:24]  # Обрезать длинные названия
        level = building['level']
        index = building['index']
        y_coord = building['y_coord']

        print(f"{i:<4} {name:<25} Lv.{level:<5} #{index:<6} {y_coord:<8}")

    if len(buildings) > 15:
        print(f"... и ещё {len(buildings) - 15} зданий")

    # ===== ШАГ 6: Пример использования =====
    print("\n💡 ПРИМЕР ИСПОЛЬЗОВАНИЯ")
    print_separator("-")

    if buildings:
        example = buildings[0]
        print(f"Для перехода к зданию '{example['name']}':")
        print(f"  Уровень: {example['level']}")
        print(f"  Индекс: #{example['index']}")
        print(f"  Координаты кнопки: {example['button_coord']}")
        print(f"\n  Python код:")
        print(f"  tap(emulator, {example['button_coord'][0]}, {example['button_coord'][1]})")

    # ===== ШАГ 7: Debug файлы =====
    print("\n📁 DEBUG ФАЙЛЫ")
    print_separator("-")
    print("Debug скриншоты сохранены в:")
    print("  data/screenshots/debug/ocr/")
    print("\n🎨 Цветовая кодировка bbox:")
    print("   🟢 Зелёный  = отличная уверенность (>0.9)")
    print("   🟡 Жёлтый   = хорошая уверенность (>0.7)")
    print("   🔴 Красный  = низкая уверенность (<0.7)")

    # ===== ФИНАЛ =====
    print_separator()
    print("✅ ТЕСТ УСПЕШНО ЗАВЕРШЁН")
    print_separator()

    return True


def test_cpu_vs_gpu_comparison():
    """
    Сравнивает производительность CPU и GPU

    Требует 2 прогона теста:
    1. С GPU (по умолчанию)
    2. С CPU (force_cpu=True)
    """
    print_separator("=")
    print("⚔️  CPU vs GPU СРАВНЕНИЕ")
    print_separator("=")

    emulator = {
        'id': 1,
        'name': 'LDPlayer-Test',
        'port': 5556
    }

    # Получить скриншот
    screenshot = get_screenshot(emulator)
    if screenshot is None:
        print("❌ Не удалось получить скриншот")
        return

    results = {}

    # Тест 1: GPU
    print("\n🎮 Тест 1: GPU режим")
    print("-" * 70)
    ocr_gpu = get_ocr_engine(force_cpu=False)

    times_gpu = []
    for i in range(3):
        start = time.time()
        _ = ocr_gpu.parse_navigation_panel(screenshot, emulator['id'])
        elapsed = time.time() - start
        times_gpu.append(elapsed)

    results['gpu'] = sum(times_gpu) / len(times_gpu)
    print(f"Среднее время (GPU): {results['gpu']*1000:.2f} мс")

    # Тест 2: CPU
    print("\n💻 Тест 2: CPU режим")
    print("-" * 70)

    # Пересоздать OCR для CPU (не используем singleton)
    from utils.ocr_engine import OCREngine
    ocr_cpu = OCREngine(force_cpu=True)

    times_cpu = []
    for i in range(3):
        start = time.time()
        _ = ocr_cpu.parse_navigation_panel(screenshot, emulator['id'])
        elapsed = time.time() - start
        times_cpu.append(elapsed)

    results['cpu'] = sum(times_cpu) / len(times_cpu)
    print(f"Среднее время (CPU): {results['cpu']*1000:.2f} мс")

    # Сравнение
    print("\n📊 ИТОГОВОЕ СРАВНЕНИЕ")
    print_separator("-")
    speedup = results['cpu'] / results['gpu']
    print(f"GPU:     {results['gpu']*1000:.2f} мс")
    print(f"CPU:     {results['cpu']*1000:.2f} мс")
    print(f"Ускорение: {speedup:.2f}x")

    if speedup >= 4.0:
        print("\n🏆 GPU даёт отличное ускорение!")
    elif speedup >= 2.0:
        print("\n✅ GPU даёт хорошее ускорение")
    elif speedup >= 1.2:
        print("\n⚠️  GPU даёт небольшое ускорение")
    else:
        print("\n❌ GPU не даёт ускорения (проблема с настройкой)")

    print_separator("=")


if __name__ == "__main__":
    try:
        # Основной тест
        success = test_ocr_on_emulator()

        # Опционально: сравнение CPU vs GPU
        # Раскомментируйте если хотите сравнить производительность
        # if success:
        #     test_cpu_vs_gpu_comparison()

    except KeyboardInterrupt:
        print("\n\n⏸️  Тест прерван пользователем")
    except Exception as e:
        print(f"\n\n❌ ОШИБКА: {e}")
        logger.exception(e)
        print("\n🔍 Проверьте:")
        print("  1. PaddlePaddle GPU установлен?")
        print("  2. CUDA Toolkit 12 установлен?")
        print("  3. cuDNN файлы скопированы в папку CUDA?")
        print("  4. Эмулятор запущен и доступен через ADB?")