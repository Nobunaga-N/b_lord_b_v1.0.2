"""
Тест модуля улучшения зданий
Запуск: python tests/test_building_upgrade.py
"""

import sys
import time
from utils.logger import logger
from functions.building.navigation_panel import NavigationPanel
from functions.building.building_upgrade import BuildingUpgrade
from functions.building.building_database import BuildingDatabase

# Настроить логирование
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)


def test_upgrade_building():
    """Тест улучшения здания"""

    # ========== НАСТРОЙКИ ТЕСТА ==========
    emulator = {
        'id': 0,
        'name': 'LDPlayer',
        'port': 5556
    }

    # Здание для теста (ИЗМЕНИ НА НУЖНОЕ!)
    test_building_name = "Склад Грунта"  # Название здания
    test_building_index = 1  # Индекс (для множественных зданий)

    # =====================================

    logger.info("=" * 80)
    logger.info("🧪 ТЕСТ УЛУЧШЕНИЯ ЗДАНИЯ")
    logger.info("=" * 80)
    logger.info(f"📍 Эмулятор: {emulator['name']} (ID: {emulator['id']})")
    logger.info(f"🏗️ Здание: {test_building_name} #{test_building_index}")
    logger.info("=" * 80)

    # Инициализация компонентов
    panel = NavigationPanel()
    upgrade = BuildingUpgrade()
    db = BuildingDatabase()

    # ШАГ 1: Открыть панель навигации
    logger.info("\n📌 ШАГ 1: Открытие панели навигации...")
    if not panel.open_navigation_panel(emulator):
        logger.error("❌ Не удалось открыть панель навигации")
        return

    input("✅ Панель открыта. Нажми Enter для продолжения...")

    # ШАГ 2: Перейти к зданию
    logger.info(f"\n📌 ШАГ 2: Переход к зданию '{test_building_name}'...")
    if not panel.navigate_to_building(emulator, test_building_name):
        logger.error(f"❌ Не удалось перейти к зданию '{test_building_name}'")
        return

    logger.success(f"✅ Перешли к зданию '{test_building_name}'")
    time.sleep(2)  # Пауза чтобы увидеть

    input("✅ Здание в центре экрана. Нажми Enter для начала улучшения...")

    # ШАГ 3: Улучшить здание
    logger.info(f"\n📌 ШАГ 3: Улучшение здания...")
    success, timer_seconds = upgrade.upgrade_building(
        emulator,
        test_building_name,
        test_building_index
    )

    if success:
        if timer_seconds == 0:
            logger.success("🚀 Улучшение завершилось мгновенно (помощь альянса)")
        else:
            logger.success(f"✅ Улучшение началось!")
            logger.info(f"⏱️ Таймер: {timer_seconds} секунд ({timer_seconds // 60} минут)")

            # ШАГ 4: Обновление БД (симуляция)
            logger.info(f"\n📌 ШАГ 4: Обновление базы данных...")
            logger.info("TODO: Здесь будет вызов db.set_building_upgrading(...)")
            logger.info(f"  - Эмулятор: {emulator['id']}")
            logger.info(f"  - Здание: {test_building_name} #{test_building_index}")
            logger.info(f"  - Таймер: {timer_seconds} сек")
    else:
        logger.error("❌ Не удалось улучшить здание")
        logger.warning("⚠️ Возможные причины:")
        logger.warning("  1. Недостаточно ресурсов")
        logger.warning("  2. Нет свободных строителей")
        logger.warning("  3. Здание уже улучшается")

    logger.info("\n" + "=" * 80)
    logger.success("✅ ТЕСТ ЗАВЕРШЁН!")
    logger.info("=" * 80)


def test_upgrade_sequence():
    """Тест последовательного улучшения нескольких зданий"""

    # ========== НАСТРОЙКИ ТЕСТА ==========
    emulator = {
        'id': 0,
        'name': 'LDPlayer',
        'port': 5556
    }

    # Список зданий для улучшения
    buildings_to_upgrade = [
        ("Склад Грунта", 1),
        ("Склад Грунта", 2),
        ("Склад Грунта", 1),
    ]

    # =====================================

    logger.info("=" * 80)
    logger.info("🧪 ТЕСТ ПОСЛЕДОВАТЕЛЬНОГО УЛУЧШЕНИЯ")
    logger.info("=" * 80)
    logger.info(f"📍 Эмулятор: {emulator['name']} (ID: {emulator['id']})")
    logger.info(f"🏗️ Зданий в списке: {len(buildings_to_upgrade)}")
    logger.info("=" * 80)

    # Инициализация
    panel = NavigationPanel()
    upgrade = BuildingUpgrade()

    # Счетчики
    success_count = 0
    failed_count = 0

    for idx, (building_name, building_index) in enumerate(buildings_to_upgrade, 1):
        logger.info(f"\n{'=' * 80}")
        logger.info(f"📍 ЗДАНИЕ {idx}/{len(buildings_to_upgrade)}: {building_name} #{building_index}")
        logger.info(f"{'=' * 80}")

        # Открыть панель
        if not panel.open_navigation_panel(emulator):
            logger.error("❌ Не удалось открыть панель")
            failed_count += 1
            continue

        # Перейти к зданию
        if not panel.navigate_to_building(emulator, building_name):
            logger.error(f"❌ Не удалось перейти к '{building_name}'")
            failed_count += 1
            continue

        time.sleep(2)

        # Улучшить
        success, timer = upgrade.upgrade_building(emulator, building_name, building_index)

        if success:
            success_count += 1
            logger.success(f"✅ Успешно: {building_name} #{building_index}")
        else:
            failed_count += 1
            logger.error(f"❌ Провал: {building_name} #{building_index}")

        # Пауза между зданиями
        time.sleep(3)

    # Финальный отчет
    logger.info("\n" + "=" * 80)
    logger.info("📊 ФИНАЛЬНЫЙ ОТЧЕТ")
    logger.info("=" * 80)
    logger.success(f"✅ Успешно: {success_count}")
    logger.error(f"❌ Провалов: {failed_count}")
    logger.info(f"📈 Процент успеха: {success_count / len(buildings_to_upgrade) * 100:.1f}%")
    logger.info("=" * 80)


if __name__ == "__main__":
    print("\n🎯 ВЫБЕРИ РЕЖИМ ТЕСТА:")
    print("1. Тест одного здания (с паузами)")
    print("2. Тест последовательности зданий (автоматически)")
    print()

    choice = input("Введи номер (1 или 2): ").strip()

    if choice == "1":
        test_upgrade_building()
    elif choice == "2":
        test_upgrade_sequence()
    else:
        print("❌ Неверный выбор!")