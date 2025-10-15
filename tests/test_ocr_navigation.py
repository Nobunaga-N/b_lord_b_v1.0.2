"""
Тест OCR на панели навигации (PaddleX 3.2.x)

Проверяет:
- Инициализацию OCR с GPU
- Получение скриншота с эмулятора
- Парсинг панели навигации
- Производительность (бенчмарк)
- Сохранение debug скриншотов с bbox

Как запустить:
1. Запустить эмулятор LDPlayer (любой порт)
2. Открыть игру Beast Lord
3. Открыть панель навигации → вкладка "Список зданий"
4. Развернуть любой раздел (например, "Битва")
5. python tests/test_ocr_navigation.py
"""

import sys
import time
from pathlib import Path
from datetime import datetime

# Добавить корневую директорию в path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from utils.ocr_engine import OCREngine

try:
    from utils.image_recognition import get_screenshot
    from utils.adb_controller import execute_command
    ADB_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ ADB утилиты не найдены, используем тестовое изображение")
    ADB_AVAILABLE = False


def get_first_connected_emulator():
    """Найти первый подключенный эмулятор"""
    result = execute_command("adb devices")
    lines = result.strip().split('\n')

    for line in lines[1:]:  # Пропустить заголовок
        if 'device' in line:
            parts = line.split()
            if len(parts) >= 2:
                device = parts[0]
                # Извлечь порт
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

    # Найти первый доступный эмулятор
    emulator = get_first_connected_emulator()
    if not emulator:
        logger.error("❌ Нет подключенных эмуляторов!")
        logger.info("💡 Запустите эмулятор и откройте панель навигации в игре")
        return False

    logger.info(f"📱 Используется эмулятор: {emulator['name']} (порт {emulator['port']})")

    # Инициализация OCR
    logger.info("\n🔧 Инициализация OCR...")
    ocr = OCREngine(lang='ru', force_cpu=False)
    ocr.set_debug_mode(True)  # Включить debug режим

    # Получить скриншот
    logger.info("\n📸 Получение скриншота...")
    logger.info(f"Скриншот получен: {emulator['name']} (540x960)")

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
        elapsed = (time.time() - start_time) * 1000  # в миллисекундах
        times.append(elapsed)

        if i == 0:
            all_buildings = buildings  # Сохранить результаты первого прогона

        logger.info(f"   Прогон {i+1}: {elapsed:.0f} мс")

    avg_time = sum(times) / len(times)
    logger.info(f"\n   📊 Среднее время: {avg_time:.0f} мс")

    # Оценка производительности
    if avg_time < 200:
        logger.success("   🏆 ОТЛИЧНО! GPU работает на полную!")
    elif avg_time < 500:
        logger.info("   ⚡ ХОРОШО! GPU ускоряет обработку")
    elif avg_time < 1000:
        logger.warning("   ⚠️ СРЕДНЕ. Возможно GPU не используется")
    else:
        logger.error("   ❌ МЕДЛЕННО! GPU точно не работает")

    # Результаты распознавания
    logger.info("\n📊 РЕЗУЛЬТАТЫ РАСПОЗНАВАНИЯ:")
    logger.info(f"   Найдено зданий: {len(all_buildings)}")

    if all_buildings:
        logger.info("\n   Список зданий:")
        for i, building in enumerate(all_buildings, 1):
            logger.info(
                f"   {i}. {building['name']:30} "
                f"Lv.{building['level']:2} "
                f"(Y: {building['y_coord']:3})"
            )

        # Сохранить результаты в файл
        save_results_to_file(all_buildings)
    else:
        logger.warning("   ⚠️ Здания не распознаны!")
        logger.info("   💡 Убедитесь что:")
        logger.info("      - Открыта панель навигации")
        logger.info("      - Выбрана вкладка 'Список зданий'")
        logger.info("      - Один из разделов развёрнут")

    return True


def test_with_sample_image():
    """Тест на тестовом изображении (если нет эмулятора)"""
    logger.info("=" * 60)
    logger.info("🧪 ТЕСТ OCR НА ТЕСТОВОМ ИЗОБРАЖЕНИИ")
    logger.info("=" * 60)

    # Проверить наличие тестового изображения
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

    # Инициализация OCR
    logger.info("\n🔧 Инициализация OCR...")
    ocr = OCREngine(lang='ru', force_cpu=False)
    ocr.set_debug_mode(True)

    # Парсинг
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
                f"(Y: {building['y_coord']:3})"
            )

        save_results_to_file(buildings)
    else:
        logger.warning("   ⚠️ Здания не распознаны!")
        logger.info("   💡 Проверьте скриншот и убедитесь что на нём видна панель навигации")

    return True


def save_results_to_file(buildings: list):
    """Сохранить результаты в текстовый файл"""
    results_dir = Path("data/screenshots/debug/ocr")
    results_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = results_dir / f"results_{timestamp}.txt"

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("РЕЗУЛЬТАТЫ РАСПОЗНАВАНИЯ ПАНЕЛИ НАВИГАЦИИ\n")
        f.write("=" * 60 + "\n")
        f.write(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Найдено зданий: {len(buildings)}\n\n")

        for i, building in enumerate(buildings, 1):
            f.write(f"{i}. {building['name']} - Lv.{building['level']}\n")
            f.write(f"   Y-координата: {building['y_coord']}\n")
            f.write(f"   Кнопка 'Перейти': {building['button_coord']}\n\n")

    logger.success(f"💾 Результаты сохранены: {filename}")


def main():
    """Главная функция теста"""
    logger.remove()  # Удалить стандартный handler
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
        level="DEBUG"
    )

    # Выбор режима теста
    if ADB_AVAILABLE:
        success = test_with_emulator()
    else:
        success = test_with_sample_image()

    # Итоги
    logger.info("\n" + "=" * 60)
    if success:
        logger.success("✅ ТЕСТ ЗАВЕРШЁН УСПЕШНО!")
        logger.info("\n💡 Debug скриншоты сохранены в: data/screenshots/debug/ocr/")
        logger.info("   Проверьте их чтобы увидеть bbox и распознанный текст")
    else:
        logger.error("❌ ТЕСТ ЗАВЕРШЁН С ОШИБКАМИ")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()