"""
Тест панели навигации
"""

import sys
from utils.logger import logger
from functions.building.navigation_panel import NavigationPanel

# Настроить логирование
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
    level="DEBUG"
)

def test_navigation_panel():
    """Тест панели навигации"""

    # Создать объект эмулятора (замени на свой!)
    emulator = {
        'id': 0,
        'name': 'LDPlayer',
        'port': 5556
    }

    # Инициализировать панель
    panel = NavigationPanel()

    # ТЕСТ 1: Открытие панели
    logger.info("\n=== ТЕСТ 1: Открытие панели ===")
    success = panel.open_navigation_panel(emulator)
    logger.info(f"Результат: {'✅ Успешно' if success else '❌ Ошибка'}")

    input("\nНажми Enter для продолжения...")

    # ТЕСТ 2: Переключение на "Список зданий"
    logger.info("\n=== ТЕСТ 2: Переключение на 'Список зданий' ===")
    panel.switch_to_buildings_tab(emulator)

    input("\nНажми Enter для продолжения...")

    # ТЕСТ 3: Сворачивание всех разделов
    logger.info("\n=== ТЕСТ 3: Сворачивание всех разделов ===")
    success = panel.collapse_all_sections(emulator)
    logger.info(f"Результат: {'✅ Все свёрнуто' if success else '❌ Ошибка'}")

    input("\nНажми Enter для продолжения...")

    # ТЕСТ 4: Получение списка зданий в разделе "Развитие"
    logger.info("\n=== ТЕСТ 4: Парсинг зданий в разделе 'Развитие' ===")
    buildings = panel.get_buildings_in_section(emulator, "Развитие")

    logger.info(f"\nНайдено зданий: {len(buildings)}")
    for b in buildings:
        logger.info(f"  - {b['name']} Lv.{b['level']} (Y: {b['y']})")

    input("\nНажми Enter для продолжения...")

    # ТЕСТ 5: Переход к зданию
    logger.info("\n=== ТЕСТ 5: Переход к зданию ===")
    if buildings:
        test_building = buildings[0]['name']
        logger.info(f"Попытка перейти к: {test_building}")
        success = panel.go_to_building(emulator, test_building)
        logger.info(f"Результат: {'✅ Успешно' if success else '❌ Ошибка'}")

    logger.success("\n✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ!")

if __name__ == "__main__":
    test_navigation_panel()