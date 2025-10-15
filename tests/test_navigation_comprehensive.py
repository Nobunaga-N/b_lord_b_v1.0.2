"""
Comprehensive тест панели навигации
Проверяет доступ ко ВСЕМ testable зданиям из конфигурации
"""

import sys
import time
from datetime import datetime
from typing import List, Dict, Tuple
from utils.logger import logger
from functions.building.navigation_panel import NavigationPanel

# Настроить логирование
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)


class NavigationTester:
    """Класс для comprehensive тестирования навигации"""

    def __init__(self, emulator: Dict):
        """
        Инициализация тестера

        Args:
            emulator: объект эмулятора
        """
        self.emulator = emulator
        self.panel = NavigationPanel()

        # Статистика
        self.total_buildings = 0
        self.success_count = 0
        self.failed_count = 0
        self.results = []  # [{"name": "...", "status": "✅/❌", "time": X, "error": "..."}, ...]

        # Настройки
        self.pause_between_tests = 1.0  # Секунды между тестами
        self.manual_check_mode = False  # Ручная проверка после каждого здания

    def run_full_test(self, filter_section: str = None, filter_subsection: str = None) -> Dict:
        """
        Запустить полный тест всех testable зданий

        Args:
            filter_section: фильтр по разделу (например, "Ресурсы")
            filter_subsection: фильтр по подвкладке (например, "Фрукты")

        Returns:
            dict: статистика тестирования
        """
        logger.info("=" * 80)
        logger.info("🚀 COMPREHENSIVE TEST - ПАНЕЛЬ НАВИГАЦИИ")
        logger.info("=" * 80)

        # Получить все testable здания
        all_buildings = self.panel.get_all_testable_buildings()

        # Применить фильтры
        if filter_section:
            all_buildings = [b for b in all_buildings if b.get('section') == filter_section]
            logger.info(f"📌 Фильтр по разделу: {filter_section}")

        if filter_subsection:
            all_buildings = [b for b in all_buildings if b.get('subsection') == filter_subsection]
            logger.info(f"📌 Фильтр по подвкладке: {filter_subsection}")

        self.total_buildings = len(all_buildings)

        if self.total_buildings == 0:
            logger.warning("⚠️ Нет зданий для тестирования!")
            return self._generate_report()

        logger.info(f"📊 Всего зданий для тестирования: {self.total_buildings}")
        logger.info("-" * 80)

        # Тестирование каждого здания
        for idx, building in enumerate(all_buildings, 1):
            building_name = building['name']
            section = building.get('section', '???')
            subsection = building.get('subsection', '-')
            count = building.get('count', 1)
            from_tasks = building.get('from_tasks_tab', False)

            logger.info(f"\n[{idx}/{self.total_buildings}] 🏢 Тестирование: {building_name}")
            logger.info(f"   Раздел: {section} | Подвкладка: {subsection}")
            logger.info(f"   Количество: {count} | Из 'Список дел': {from_tasks}")

            # Тестирование
            success, elapsed_time, error = self._test_single_building(building)

            # Сохранить результат
            result = {
                'index': idx,
                'name': building_name,
                'section': section,
                'subsection': subsection,
                'count': count,
                'from_tasks_tab': from_tasks,
                'status': '✅' if success else '❌',
                'elapsed_time': elapsed_time,
                'error': error
            }
            self.results.append(result)

            # Обновить статистику
            if success:
                self.success_count += 1
                logger.success(f"   ✅ УСПЕШНО (время: {elapsed_time:.2f}с)")
            else:
                self.failed_count += 1
                logger.error(f"   ❌ ОШИБКА: {error} (время: {elapsed_time:.2f}с)")

            # Ручная проверка (если включена)
            if self.manual_check_mode and idx < self.total_buildings:
                input("\n⏸️  Нажми Enter для продолжения...")

            # Пауза между тестами
            if idx < self.total_buildings:
                time.sleep(self.pause_between_tests)

        # Генерация отчета
        return self._generate_report()

    def _test_single_building(self, building: Dict) -> Tuple[bool, float, str]:
        """
        Тестирование одного здания

        Args:
            building: конфигурация здания

        Returns:
            tuple: (success, elapsed_time, error_message)
        """
        building_name = building['name']
        start_time = time.time()

        try:
            # 1. Навигация к зданию
            success = self.panel.navigate_to_building(self.emulator, building_name)

            if not success:
                elapsed_time = time.time() - start_time
                return False, elapsed_time, "Не удалось найти или перейти к зданию"

            # 2. Закрыть панель навигации (для проверки что перешли)
            time.sleep(0.5)
            self.panel.close_navigation_panel(self.emulator)
            time.sleep(0.5)

            # 3. Открыть панель снова для следующего теста
            self.panel.open_navigation_panel(self.emulator)
            time.sleep(0.5)

            # 4. Сбросить состояние панели
            self.panel.switch_to_buildings_tab(self.emulator)
            self.panel.reset_navigation_state(self.emulator)

            elapsed_time = time.time() - start_time
            return True, elapsed_time, ""

        except Exception as e:
            elapsed_time = time.time() - start_time
            return False, elapsed_time, str(e)

    def _generate_report(self) -> Dict:
        """
        Генерация финального отчета

        Returns:
            dict: статистика тестирования
        """
        logger.info("\n" + "=" * 80)
        logger.info("📊 ФИНАЛЬНЫЙ ОТЧЕТ")
        logger.info("=" * 80)

        # Общая статистика
        success_rate = (self.success_count / self.total_buildings * 100) if self.total_buildings > 0 else 0

        logger.info(f"Всего протестировано: {self.total_buildings}")
        logger.success(f"✅ Успешно: {self.success_count}")
        logger.error(f"❌ Ошибки: {self.failed_count}")
        logger.info(f"📈 Процент успеха: {success_rate:.1f}%")

        # Детальная статистика по разделам
        logger.info("\n" + "-" * 80)
        logger.info("📂 СТАТИСТИКА ПО РАЗДЕЛАМ")
        logger.info("-" * 80)

        sections_stats = {}
        for result in self.results:
            section = result['section']
            if section not in sections_stats:
                sections_stats[section] = {'total': 0, 'success': 0, 'failed': 0}

            sections_stats[section]['total'] += 1
            if result['status'] == '✅':
                sections_stats[section]['success'] += 1
            else:
                sections_stats[section]['failed'] += 1

        for section, stats in sections_stats.items():
            rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
            logger.info(f"{section:20} | ✅ {stats['success']:2} | ❌ {stats['failed']:2} | 📈 {rate:5.1f}%")

        # Таблица всех результатов
        logger.info("\n" + "-" * 80)
        logger.info("📋 ДЕТАЛЬНЫЕ РЕЗУЛЬТАТЫ")
        logger.info("-" * 80)
        logger.info(f"{'#':<4} {'Статус':<7} {'Название':<30} {'Раздел':<20} {'Время':<8}")
        logger.info("-" * 80)

        for result in self.results:
            idx = result['index']
            status = result['status']
            name = result['name'][:29]  # Обрезаем если длинное
            section = result['section'][:19]
            elapsed = result['elapsed_time']

            log_method = logger.info if status == '✅' else logger.warning
            log_method(f"{idx:<4} {status:<7} {name:<30} {section:<20} {elapsed:>6.2f}с")

        # Ошибки
        failed_results = [r for r in self.results if r['status'] == '❌']
        if failed_results:
            logger.info("\n" + "-" * 80)
            logger.error("❌ СПИСОК ОШИБОК")
            logger.info("-" * 80)

            for result in failed_results:
                logger.error(f"[{result['index']}] {result['name']}")
                logger.error(f"    Ошибка: {result['error']}")

        # Сохранение отчета в файл
        self._save_report_to_file()

        logger.info("\n" + "=" * 80)

        return {
            'total': self.total_buildings,
            'success': self.success_count,
            'failed': self.failed_count,
            'success_rate': success_rate,
            'results': self.results
        }

    def _save_report_to_file(self):
        """Сохранить отчет в файл"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"navigation_test_report_{timestamp}.txt"

            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("COMPREHENSIVE TEST - ПАНЕЛЬ НАВИГАЦИИ\n")
                f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")

                f.write(f"Всего протестировано: {self.total_buildings}\n")
                f.write(f"✅ Успешно: {self.success_count}\n")
                f.write(f"❌ Ошибки: {self.failed_count}\n")
                f.write(f"📈 Процент успеха: {(self.success_count / self.total_buildings * 100):.1f}%\n\n")

                f.write("-" * 80 + "\n")
                f.write("ДЕТАЛЬНЫЕ РЕЗУЛЬТАТЫ\n")
                f.write("-" * 80 + "\n")

                for result in self.results:
                    f.write(f"\n[{result['index']}] {result['status']} {result['name']}\n")
                    f.write(f"    Раздел: {result['section']}\n")
                    f.write(f"    Подвкладка: {result['subsection']}\n")
                    f.write(f"    Время: {result['elapsed_time']:.2f}с\n")
                    if result['error']:
                        f.write(f"    Ошибка: {result['error']}\n")

            logger.info(f"💾 Отчет сохранен: {filename}")

        except Exception as e:
            logger.error(f"❌ Не удалось сохранить отчет: {e}")


def main():
    """Главная функция"""

    # НАСТРОЙКИ ЭМУЛЯТОРА (замени на свой!)
    emulator = {
        'id': 0,
        'name': 'LDPlayer',
        'port': 5556
    }

    # Создать тестер
    tester = NavigationTester(emulator)

    # НАСТРОЙКИ ТЕСТА
    tester.pause_between_tests = 1.0  # Пауза между зданиями (секунды)
    tester.manual_check_mode = False  # True = пауза после каждого здания для ручной проверки

    logger.info("\n🎯 РЕЖИМЫ ТЕСТИРОВАНИЯ:")
    logger.info("1. Полный тест всех зданий")
    logger.info("2. Тест конкретного раздела")
    logger.info("3. Тест конкретной подвкладки")
    logger.info("4. Быстрый тест (первые 5 зданий)")

    mode = input("\nВыбери режим (1-4): ").strip()

    if mode == '1':
        # Полный тест
        logger.info("\n🚀 Запуск полного теста...")
        stats = tester.run_full_test()

    elif mode == '2':
        # Тест раздела
        logger.info("\nДоступные разделы:")
        logger.info("- Вожак")
        logger.info("- Мегазверь")
        logger.info("- Битва")
        logger.info("- Развитие")
        logger.info("- Альянс")
        logger.info("- Ресурсы")
        logger.info("- Другие")

        section = input("\nВведи название раздела: ").strip()
        logger.info(f"\n🚀 Запуск теста раздела '{section}'...")
        stats = tester.run_full_test(filter_section=section)

    elif mode == '3':
        # Тест подвкладки
        logger.info("\nДоступные подвкладки (Ресурсы):")
        logger.info("- Фрукты")
        logger.info("- Трава")
        logger.info("- Листья")
        logger.info("- Грунт")
        logger.info("- Песок")
        logger.info("- Вода")
        logger.info("- Мед")

        subsection = input("\nВведи название подвкладки: ").strip()
        logger.info(f"\n🚀 Запуск теста подвкладки '{subsection}'...")
        stats = tester.run_full_test(filter_section="Ресурсы", filter_subsection=subsection)

    elif mode == '4':
        # Быстрый тест
        logger.info("\n🚀 Запуск быстрого теста (первые 5 зданий)...")

        all_buildings = tester.panel.get_all_testable_buildings()
        tester.total_buildings = min(5, len(all_buildings))

        for idx, building in enumerate(all_buildings[:5], 1):
            building_name = building['name']
            logger.info(f"\n[{idx}/5] 🏢 Тестирование: {building_name}")

            success, elapsed_time, error = tester._test_single_building(building)

            result = {
                'index': idx,
                'name': building_name,
                'section': building.get('section', '???'),
                'subsection': building.get('subsection', '-'),
                'count': building.get('count', 1),
                'from_tasks_tab': building.get('from_tasks_tab', False),
                'status': '✅' if success else '❌',
                'elapsed_time': elapsed_time,
                'error': error
            }
            tester.results.append(result)

            if success:
                tester.success_count += 1
                logger.success(f"   ✅ УСПЕШНО (время: {elapsed_time:.2f}с)")
            else:
                tester.failed_count += 1
                logger.error(f"   ❌ ОШИБКА: {error}")

            time.sleep(1)

        stats = tester._generate_report()

    else:
        logger.error("❌ Неверный режим!")
        return

    # Финальное сообщение
    if stats['success_rate'] >= 95:
        logger.success(f"\n🎉 ОТЛИЧНО! Процент успеха: {stats['success_rate']:.1f}%")
    elif stats['success_rate'] >= 80:
        logger.warning(f"\n⚠️ ХОРОШО, но есть ошибки. Процент успеха: {stats['success_rate']:.1f}%")
    else:
        logger.error(f"\n❌ ПЛОХО! Много ошибок. Процент успеха: {stats['success_rate']:.1f}%")


if __name__ == "__main__":
    main()