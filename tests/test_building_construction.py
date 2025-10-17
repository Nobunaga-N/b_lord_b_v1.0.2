"""
Тест модуля постройки новых зданий
Запуск: python tests/test_building_construction.py

ВАЖНО: Перед запуском убедись что:
1. Эмулятор запущен
2. Игра загружена
3. Находишься на главном экране (карта мира)
"""

import sys
import time
from utils.logger import logger
from functions.building.building_construction import BuildingConstruction
from functions.building.navigation_panel import NavigationPanel
from functions.building.building_database import BuildingDatabase

# Настроить логирование
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)


def test_single_building():
    """Тест постройки одного здания"""

    # ========== НАСТРОЙКИ ТЕСТА ==========
    emulator = {
        'id': 1,
        'name': 'LDPlayer',
        'port': 5556
    }

    # =====================================

    logger.info("=" * 80)
    logger.info("🧪 ТЕСТ ПОСТРОЙКИ НОВОГО ЗДАНИЯ")
    logger.info("=" * 80)
    logger.info(f"📍 Эмулятор: {emulator['name']} (ID: {emulator['id']})")
    logger.info("=" * 80)

    # Инициализация компонентов
    construction = BuildingConstruction()
    panel = NavigationPanel()
    db = BuildingDatabase()

    # Список доступных зданий для постройки
    logger.info("\n🏗️ ДОСТУПНЫЕ ЗДАНИЯ ДЛЯ ПОСТРОЙКИ:")
    logger.info("1. Жилище Лемуров IV (требует Лорд ≥13)")
    logger.info("2. Центр Сбора II (требует Лорд ≥13)")
    logger.info("3. Центр Сбора III (требует Лорд ≥18)")
    logger.info("4. Склад Фруктов II (требует Лорд ≥13 и Склад Фруктов ≥10)")
    logger.info("5. Склад Листьев II (требует Лорд ≥13 и Склад Листьев ≥10)")
    logger.info("6. Склад Грунта II (требует Лорд ≥13 и Склад Грунта ≥10)")
    logger.info("7. Склад Песка II (требует Лорд ≥13 и Склад Песка ≥10)")
    logger.info("8. Жилище Детенышей (5-е) (требует Лорд ≥14)")

    choice = input("\nВыбери здание (1-8): ").strip()

    # Маппинг выбора
    buildings_map = {
        '1': 'Жилище Лемуров IV',
        '2': 'Центр Сбора II',
        '3': 'Центр Сбора III',
        '4': 'Склад Фруктов II',
        '5': 'Склад Листьев II',
        '6': 'Склад Грунта II',
        '7': 'Склад Песка II',
        '8': 'Жилище Детенышей'
    }

    if choice not in buildings_map:
        logger.error("❌ Неверный выбор!")
        return

    test_building_name = buildings_map[choice]

    logger.info(f"\n🎯 Выбрано здание: {test_building_name}")
    logger.info("=" * 80)

    # Проверяем уровень Лорда
    emulator_id = emulator.get('id', 0)
    lord_level = db.get_lord_level(emulator_id)

    if lord_level == 0:
        logger.warning("⚠️ Уровень Лорда не найден в БД. Первый запуск бота?")
        logger.info("ℹ️ Запусти сначала полный цикл строительства для инициализации БД")
        input("\nНажми Enter чтобы продолжить тест в любом случае...")
    else:
        logger.info(f"📊 Уровень Лорда: {lord_level}")

    input("\n✅ Убедись что игра запущена и находишься на главном экране. Нажми Enter для начала...")

    # ШАГ 1: Постройка здания
    logger.info(f"\n📌 ШАГ 1: Постройка здания '{test_building_name}'...")
    logger.info("=" * 80)

    success = construction.construct_building(
        emulator,
        test_building_name,
        building_index=None
    )

    if success:
        logger.success(f"✅ Здание '{test_building_name}' успешно построено!")

        # ШАГ 2: Проверка через панель навигации
        logger.info(f"\n📌 ШАГ 2: Проверка что здание появилось в панели навигации...")
        time.sleep(3)  # Пауза чтобы игра обновилась

        if panel.open_navigation_panel(emulator):
            logger.success("✅ Панель навигации открыта")

            # Пробуем найти здание
            if panel.navigate_to_building(emulator, test_building_name):
                logger.success(f"✅ Здание '{test_building_name}' найдено в панели!")
                logger.info("🎉 ТЕСТ ПРОЙДЕН УСПЕШНО!")
            else:
                logger.warning(f"⚠️ Здание '{test_building_name}' не найдено в панели")
                logger.info("ℹ️ Возможно панель нужно обновить или здание строится")
        else:
            logger.warning("⚠️ Не удалось открыть панель навигации для проверки")

    else:
        logger.error(f"❌ Не удалось построить здание '{test_building_name}'")
        logger.warning("⚠️ Возможные причины:")
        logger.warning("  1. Недостаточно ресурсов")
        logger.warning("  2. Нет свободных строителей")
        logger.warning("  3. Не выполнены требования (уровень Лорда или базового здания)")
        logger.warning("  4. Здание уже построено")

    logger.info("\n" + "=" * 80)
    logger.success("✅ ТЕСТ ЗАВЕРШЁН!")
    logger.info("=" * 80)


def test_multiple_buildings():
    """Тест постройки нескольких зданий подряд"""

    # ========== НАСТРОЙКИ ТЕСТА ==========
    emulator = {
        'id': 0,
        'name': 'LDPlayer',
        'port': 5556
    }

    # СПИСОК ЗДАНИЙ ДЛЯ ПОСТРОЙКИ (ИЗМЕНИ НА НУЖНЫЕ!)
    buildings_to_construct = [
        "Склад Грунта II",
        "Склад Песка II",
        "Центр Сбора II",
    ]

    # =====================================

    logger.info("=" * 80)
    logger.info("🧪 ТЕСТ ПОСЛЕДОВАТЕЛЬНОЙ ПОСТРОЙКИ ЗДАНИЙ")
    logger.info("=" * 80)
    logger.info(f"📍 Эмулятор: {emulator['name']} (ID: {emulator['id']})")
    logger.info(f"🏗️ Зданий в списке: {len(buildings_to_construct)}")
    logger.info("=" * 80)

    # Инициализация
    construction = BuildingConstruction()
    db = BuildingDatabase()

    # Проверяем уровень Лорда
    emulator_id = emulator.get('id', 0)
    lord_level = db.get_lord_level(emulator_id)

    if lord_level > 0:
        logger.info(f"📊 Уровень Лорда: {lord_level}")
    else:
        logger.warning("⚠️ Уровень Лорда не найден в БД")

    input("\n✅ Убедись что игра запущена. Нажми Enter для начала...")

    # Счетчики
    success_count = 0
    failed_count = 0

    for idx, building_name in enumerate(buildings_to_construct, 1):
        logger.info(f"\n{'=' * 80}")
        logger.info(f"📍 ЗДАНИЕ {idx}/{len(buildings_to_construct)}: {building_name}")
        logger.info(f"{'=' * 80}")

        # Построить
        success = construction.construct_building(emulator, building_name)

        if success:
            success_count += 1
            logger.success(f"✅ Успешно: {building_name}")
        else:
            failed_count += 1
            logger.error(f"❌ Провал: {building_name}")

        # Пауза между зданиями
        if idx < len(buildings_to_construct):
            logger.info("⏳ Пауза 5 секунд перед следующим зданием...")
            time.sleep(5)

    # Финальный отчет
    logger.info("\n" + "=" * 80)
    logger.info("📊 ФИНАЛЬНЫЙ ОТЧЕТ")
    logger.info("=" * 80)
    logger.success(f"✅ Успешно построено: {success_count}")
    logger.error(f"❌ Провалов: {failed_count}")

    if len(buildings_to_construct) > 0:
        success_rate = success_count / len(buildings_to_construct) * 100
        logger.info(f"📈 Процент успеха: {success_rate:.1f}%")

    logger.info("=" * 80)


if __name__ == "__main__":
    print("\n🎯 ВЫБЕРИ РЕЖИМ ТЕСТА:")
    print("1. Тест одного здания (с ручным выбором)")
    print("2. Тест последовательности зданий (автоматически)")
    print()

    choice = input("Введи номер (1 или 2): ").strip()

    if choice == "1":
        test_single_building()
    elif choice == "2":
        test_multiple_buildings()
    else:
        print("❌ Неверный выбор!")