"""
Тест OCR на реальном эмуляторе

Проверяет:
- Инициализацию OCR с GPU
- Получение скриншота
- Парсинг панели навигации
- Производительность (бенчмарк 3 прогона)
- Debug скриншоты с bbox
"""

print("🔍 ОТЛАДКА: Скрипт запущен")
print("🔍 ОТЛАДКА: Начало импортов...")

import sys
import time
from pathlib import Path
from datetime import datetime

print("🔍 ОТЛАДКА: logger импортирован")
from loguru import logger

print("🔍 ОТЛАДКА: OCREngine импортирован")
from utils.ocr_engine import OCREngine

print("🔍 ОТЛАДКА: Проверка ADB...")

# Проверка ADB
try:
    from utils.image_recognition import get_screenshot
    from utils.adb_controller import execute_command
    ADB_AVAILABLE = True
    print("🔍 ОТЛАДКА: ADB доступен")
except ImportError:
    ADB_AVAILABLE = False
    print("🔍 ОТЛАДКА: ADB недоступен")

print(f"🔍 ОТЛАДКА: ADB_AVAILABLE = {ADB_AVAILABLE}")


def get_first_connected_emulator():
    """Найти первый подключенный эмулятор"""
    result = execute_command("adb devices")
    lines = result.strip().split('\n')

    for line in lines[1:]:
        if 'device' in line:
            parts = line.split()
            if len(parts) >= 2:
                device = parts[0]
                if 'emulator-' in device:
                    port = int(device.split('-')[1])
                elif ':' in device:
                    port = int(device.split(':')[1])
                else:
                    continue

                return {
                    'id': 0,
                    'name': f'Test_Emu_{port}',
                    'port': port
                }
    return None


def test_with_emulator():
    """Тест на реальном эмуляторе"""
    logger.info("=" * 60)
    logger.info("🧪 ТЕСТ OCR НА ЭМУЛЯТОРЕ")
    logger.info("=" * 60)

    # Найти подключенный эмулятор
    emulator = get_first_connected_emulator()
    if not emulator:
        logger.error("❌ Нет подключенных эмуляторов!")
        logger.info("💡 Запустите эмулятор и откройте панель навигации в игре")
        return False

    logger.info(f"📱 Используется эмулятор: {emulator['name']} (порт {emulator['port']})")

    # Инициализация OCR
    logger.info("\n🔧 Инициализация OCR...")
    ocr = OCREngine(lang='ru', force_cpu=False)
    ocr.set_debug_mode(True)

    # Получить скриншот (используем функцию из image_recognition.py)
    logger.info("\n📸 Получение скриншота...")
    screenshot = get_screenshot(emulator)

    if screenshot is None:
        logger.error("❌ Не удалось получить скриншот")
        return False

    logger.success(f"✅ Скриншот получен: {screenshot.shape}")

    # Бенчмарк: 3 прогона
    logger.info("\n⚡ БЕНЧМАРК (3 прогона):")
    times = []
    all_buildings = []

    for i in range(3):
        start_time = time.time()
        buildings = ocr.parse_navigation_panel(screenshot, emulator_id=1)
        elapsed = (time.time() - start_time) * 1000
        times.append(elapsed)

        if i == 0:
            all_buildings = buildings

        logger.info(f"   Прогон {i+1}: {elapsed:.0f} мс")

    avg_time = sum(times) / len(times)
    logger.info(f"\n   📊 Среднее время: {avg_time:.0f} мс")

    if avg_time < 200:
        logger.success("   🏆 ОТЛИЧНО! GPU работает на полную!")
    elif avg_time < 500:
        logger.info("   ⚡ ХОРОШО! GPU ускоряет обработку")
    elif avg_time < 1000:
        logger.warning("   ⚠️ СРЕДНЕ. Возможно GPU не используется")
    else:
        logger.error("   ❌ МЕДЛЕННО! GPU точно не работает")

    # Результаты
    logger.info("\n📊 РЕЗУЛЬТАТЫ РАСПОЗНАВАНИЯ:")
    logger.info(f"   Найдено зданий: {len(all_buildings)}")

    if all_buildings:
        logger.info("\n   Список зданий:")
        for i, building in enumerate(all_buildings, 1):
            logger.info(
                f"   {i}. {building['name']:30} "
                f"Lv.{building['level']:2} "
                f"(Y: {building['y']:3})"
            )
        save_results_to_file(all_buildings)
    else:
        logger.warning("   ⚠️ Здания не распознаны!")

    return True


def test_with_sample_image():
    """Тест на тестовом изображении"""
    logger.info("=" * 60)
    logger.info("🧪 ТЕСТ OCR НА ТЕСТОВОМ ИЗОБРАЖЕНИИ")
    logger.info("=" * 60)

    sample_path = Path("data/screenshots/debug/navigation_sample.png")

    if not sample_path.exists():
        logger.error(f"❌ Тестовое изображение не найдено: {sample_path}")
        logger.info("💡 Сделайте скриншот панели навигации и сохраните по этому пути")
        return False

    import cv2
    screenshot = cv2.imread(str(sample_path))

    if screenshot is None:
        logger.error("❌ Не удалось загрузить изображение")
        return False

    logger.success(f"✅ Изображение загружено: {screenshot.shape}")

    logger.info("\n🔧 Инициализация OCR...")
    ocr = OCREngine(lang='ru', force_cpu=False)
    ocr.set_debug_mode(True)

    logger.info("\n📊 Парсинг панели навигации...")
    start_time = time.time()
    buildings = ocr.parse_navigation_panel(screenshot, emulator_id=99)
    elapsed = (time.time() - start_time) * 1000

    logger.info(f"⏱️ Время обработки: {elapsed:.0f} мс")
    logger.info(f"📊 Найдено зданий: {len(buildings)}")

    if buildings:
        logger.info("\n   Список зданий:")
        for i, building in enumerate(buildings, 1):
            logger.info(
                f"   {i}. {building['name']:30} "
                f"Lv.{building['level']:2} "
                f"(Y: {building['y']:3})"
            )
        save_results_to_file(buildings)
    else:
        logger.warning("   ⚠️ Здания не распознаны!")

    return True


def save_results_to_file(buildings: list):
    """Сохранить результаты в файл"""
    results_dir = Path("data/screenshots/debug/ocr")
    results_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = results_dir / f"results_{timestamp}.txt"

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("РЕЗУЛЬТАТЫ РАСПОЗНАВАНИЯ\n")
        f.write("=" * 60 + "\n")
        f.write(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Найдено зданий: {len(buildings)}\n\n")

        for i, building in enumerate(buildings, 1):
            f.write(f"{i}. {building['name']} - Lv.{building['level']}\n")
            f.write(f"   Y: {building['y']}\n\n")

    logger.success(f"💾 Результаты сохранены: {filename}")


def main():
    """Главная функция теста"""
    print("🔍 ОТЛАДКА: main() вызвана!")

    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
        level="DEBUG"
    )

    # Выбор режима
    if ADB_AVAILABLE:
        success = test_with_emulator()
    else:
        success = test_with_sample_image()

    # Итоги
    logger.info("\n" + "=" * 60)
    if success:
        logger.success("✅ ТЕСТ ЗАВЕРШЁН УСПЕШНО!")
        logger.info("\n💡 Debug скриншоты: data/screenshots/debug/ocr/")
    else:
        logger.error("❌ ТЕСТ ЗАВЕРШЁН С ОШИБКАМИ")
    logger.info("=" * 60)


print("🔍 ОТЛАДКА: Проверка __name__...")
print(f"🔍 ОТЛАДКА: __name__ = '{__name__}'")

if __name__ == "__main__":
    print("🔍 ОТЛАДКА: Условие __name__ == '__main__' выполнено!")
    main()
else:
    print(f"🔍 ОТЛАДКА: Условие НЕ выполнено! __name__ = '{__name__}'")