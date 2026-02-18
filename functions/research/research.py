"""
Функция: Эволюция (Исследования)
Главный класс — связывает EvolutionDatabase, EvolutionUpgrade, планировщик

Процесс:
1. Инициализация (первый запуск → первичное сканирование уровней)
2. Проверить слот исследования (свободен / занят)
3. Определить следующую технологию (EvolutionDatabase)
4. Исследовать технологию (EvolutionUpgrade)
5. Обновить БД (таймер, статус)

Версия: 1.0
Дата создания: 2025-02-18
"""

import time
from datetime import datetime
from typing import Optional

from functions.base_function import BaseFunction
from functions.research.evolution_database import EvolutionDatabase
from functions.research.evolution_upgrade import EvolutionUpgrade
from utils.logger import logger
from utils.adb_controller import press_key


class ResearchFunction(BaseFunction):
    """
    Главная функция эволюции (исследований)

    Аналог BuildingFunction, но для технологий.
    1 слот исследования на все уровни Лорда.
    """

    def __init__(self, emulator):
        """Инициализация функции эволюции"""
        super().__init__(emulator)
        self.name = "ResearchFunction"

        # Компоненты
        self.db = EvolutionDatabase()
        self.upgrade = EvolutionUpgrade()

        logger.info(f"[{self.emulator_name}] ✅ ResearchFunction инициализирована")

    # ===== МЕТОД ДЛЯ ПЛАНИРОВЩИКА =====

    @staticmethod
    def get_next_event_time(emulator_id: int) -> Optional[datetime]:
        """
        Когда эволюции потребуется эмулятор?

        Лёгкая проверка через БД без запуска эмулятора.
        Вызывается планировщиком для определения времени запуска.

        Логика:
        1. Нет записей в БД → datetime.min (новый эмулятор, первичное сканирование)
        2. Эволюция заморожена → время разморозки
        3. Слот исследования занят → время завершения
        4. Слот свободен + есть что качать → datetime.now()
        5. Всё прокачано → None

        Обработка ошибок:
        - Таблица buildings не существует → уровень Лорда 10 по умолчанию
        - Незавершённая инициализация → datetime.min (повторить)

        Returns:
            datetime — когда нужен эмулятор
            None — эмулятор не нужен для эволюции
        """
        db = EvolutionDatabase()

        try:
            # 1. Проверяем состояние инициализации
            if not db.has_evolutions(emulator_id):
                return datetime.min  # Первичная инициализация

            # 1.1 Записи есть, но сканирование не завершено?
            if not db.is_scan_complete(emulator_id):
                logger.debug(f"[Emulator {emulator_id}] Сканирование эволюции "
                             f"не завершено — требуется повтор")
                return datetime.min

            # 2. Эволюция заморожена?
            if db.is_evolution_frozen(emulator_id):
                freeze_until = db.get_evolution_freeze_until(emulator_id)
                return freeze_until

            # 3. Проверить слот (auto-complete если таймер истёк)
            db.check_and_complete_research(emulator_id)

            if db.is_slot_busy(emulator_id):
                finish_time = db.get_nearest_research_finish_time(emulator_id)
                return finish_time

            # 4. Слот свободен — есть что качать?
            if db.has_techs_to_research(emulator_id):
                return datetime.now()

            # 5. Всё прокачано
            return None

        except Exception as e:
            logger.error(f"[Emulator {emulator_id}] Ошибка в "
                         f"ResearchFunction.get_next_event_time: {e}")
            # Вместо None возвращаем datetime.min чтобы попробовать
            # инициализацию заново
            return datetime.min

    # ===== ПРОВЕРКА ГОТОВНОСТИ =====

    def can_execute(self) -> bool:
        """
        Можно ли выполнять эволюцию сейчас?

        Проверки:
        1. Инициализация при первом запуске
        2. Эволюция не заморожена
        3. Слот исследования свободен
        4. Есть технологии для исследования
        """
        emulator_id = self.emulator.get('id', 0)

        # ПРОВЕРКА 0: Первичная инициализация
        if not self._ensure_initialized():
            return False

        # ПРОВЕРКА 1: Заморозка эволюции
        if self.db.is_evolution_frozen(emulator_id):
            freeze_until = self.db.get_evolution_freeze_until(emulator_id)
            if freeze_until:
                logger.debug(f"[{self.emulator_name}] ❄️ Эволюция заморожена "
                           f"до {freeze_until.strftime('%H:%M:%S')}")
            return False

        # ПРОВЕРКА 2: Auto-complete завершённых исследований
        self.db.check_and_complete_research(emulator_id)

        # ПРОВЕРКА 3: Слот исследования свободен?
        if self.db.is_slot_busy(emulator_id):
            finish_time = self.db.get_slot_finish_time(emulator_id)
            if finish_time:
                logger.debug(f"[{self.emulator_name}] 🔬 Слот занят, "
                           f"завершение: {finish_time.strftime('%H:%M:%S')}")
            return False

        # ПРОВЕРКА 4: Есть что качать?
        next_tech = self.db.get_next_tech_to_research(emulator_id)
        if not next_tech:
            logger.debug(f"[{self.emulator_name}] 🎯 Все доступные технологии прокачаны")
            return False

        logger.debug(f"[{self.emulator_name}] ✅ Можно качать: "
                   f"{next_tech['tech_name']} ({next_tech['section_name']})")
        return True

    # ===== ОСНОВНАЯ ЛОГИКА =====

    def execute(self) -> bool:
        """
        Выполнить исследование следующей технологии

        Процесс:
        1. Определить следующую технологию из БД
        2. Получить конфиг свайпов для раздела
        3. Вызвать EvolutionUpgrade.research_tech()
        4. Обработать результат

        Добавлена логика:
        - Если следующая технология в отложенном разделе → досканировать раздел
        """
        emulator_id = self.emulator.get('id', 0)

        # Определить технологию
        next_tech = self.db.get_next_tech_to_research(emulator_id)
        if not next_tech:
            logger.info(f"[{self.emulator_name}] ✅ Нечего исследовать")
            return True

        tech_name = next_tech['tech_name']
        section_name = next_tech['section_name']
        swipe_group = next_tech['swipe_group']

        # ПРОВЕРКА: Нужно ли досканировать отложенный раздел?
        if self.db.needs_deferred_scan(emulator_id, section_name):
            logger.info(f"[{self.emulator_name}] 📡 Досканирование отложенного "
                        f"раздела: {section_name}")
            if not self._scan_deferred_section(emulator_id, section_name):
                logger.warning(f"[{self.emulator_name}] ⚠️ Не удалось отсканировать "
                               f"{section_name} — пропускаем")
                # Не фатально — бот продолжит с текущими данными

        logger.info(f"[{self.emulator_name}] 🧬 Следующая технология: "
                    f"{tech_name} ({section_name}) "
                    f"Lv.{next_tech['current_level']}/{next_tech['target_level']}")

        # Получить конфиг свайпов
        swipe_config = self.db.get_swipe_config(section_name)

        # Исследовать
        status, timer_seconds = self.upgrade.research_tech(
            self.emulator,
            tech_name=tech_name,
            section_name=section_name,
            swipe_config=swipe_config,
            swipe_group=swipe_group
        )

        # Обработать результат
        if status == "started":
            if timer_seconds:
                self.db.start_research(emulator_id, tech_name,
                                       section_name, timer_seconds)
                logger.success(
                    f"[{self.emulator_name}] ✅ Исследование начато: {tech_name} "
                    f"({EvolutionUpgrade._format_time(timer_seconds)})"
                )
            else:
                logger.warning(f"[{self.emulator_name}] ⚠️ Таймер не спарсился, "
                               f"ставим 7200с по умолчанию")
                self.db.start_research(emulator_id, tech_name,
                                       section_name, 7200)
            return True

        elif status == "no_resources":
            self.db.freeze_evolution(emulator_id, hours=4,
                                     reason="Нехватка ресурсов для эволюции")
            logger.warning(f"[{self.emulator_name}] ❄️ Эволюция заморожена на 4 часа "
                           f"(нехватка ресурсов)")
            return False

        else:  # "error"
            logger.error(f"[{self.emulator_name}] ❌ Ошибка при исследовании "
                         f"{tech_name}")
            return False

    # ==================== НОВЫЙ МЕТОД: досканирование отложенного раздела ====================

    def _scan_deferred_section(self, emulator_id: int,
                               section_name: str) -> bool:
        """
        Досканировать отложенный раздел (Поход Войска II, Походный Отряд III)

        Вызывается перед первым исследованием технологии из такого раздела.

        Returns:
            bool: True если сканирование успешно
        """
        logger.info(f"[{self.emulator_name}] 📂 Досканирование: {section_name}")

        # Открыть окно Эволюции
        if not self.upgrade.open_evolution_window(self.emulator):
            logger.error(f"[{self.emulator_name}] ❌ Не удалось открыть окно Эволюции")
            return False

        # Перейти в раздел
        if not self.upgrade.navigate_to_section(self.emulator, section_name):
            logger.warning(f"[{self.emulator_name}] ⚠️ Раздел не найден: "
                           f"{section_name} — возможно ещё не открыт в игре")
            press_key(self.emulator, "ESC")
            time.sleep(0.5)
            return False

        # Сканируем
        techs_in_section = self.db.get_techs_by_section(emulator_id,
                                                        section_name)
        max_group = max(t['swipe_group'] for t in techs_in_section) \
            if techs_in_section else 0
        swipe_config = self.db.get_swipe_config(section_name)

        scanned = self.upgrade.scan_section_levels(
            self.emulator, section_name, swipe_config, max_group
        )

        matched = self._match_scanned_to_db(emulator_id, section_name,
                                            scanned, techs_in_section)

        logger.info(f"[{self.emulator_name}] 📊 {section_name}: "
                    f"сопоставлено {matched}/{len(techs_in_section)}")

        # Закрываем раздел + окно Эволюции
        press_key(self.emulator, "ESC")
        time.sleep(0.5)
        press_key(self.emulator, "ESC")
        time.sleep(0.5)

        return True

    # ===== ИНИЦИАЛИЗАЦИЯ =====

    def _ensure_initialized(self) -> bool:
        """
        Убедиться что эволюция инициализирована для этого эмулятора

        Обрабатывает 3 состояния:
        1. Нет записей → полная инициализация (БД + сканирование)
        2. Записи есть, сканирование не завершено → повторное сканирование
        3. Всё ОК → return True
        """
        emulator_id = self.emulator.get('id', 0)

        # Состояние 3: Полностью инициализировано
        if self.db.has_evolutions(emulator_id) and \
           self.db.is_scan_complete(emulator_id):
            return True

        # Состояние 2: Записи есть, но сканирование не завершено
        if self.db.has_evolutions(emulator_id):
            logger.warning(f"[{self.emulator_name}] ⚠️ Обнаружена незавершённая "
                          f"инициализация — сбрасываю и начинаю заново")
            self.db.reset_initialization(emulator_id)

        # Состояние 1: Полная инициализация с нуля
        logger.info(f"[{self.emulator_name}] 🆕 Первый запуск эволюции — инициализация...")

        # ШАГ 1: Создать записи в БД
        if not self.db.initialize_evolutions_for_emulator(emulator_id):
            logger.error(f"[{self.emulator_name}] ❌ Не удалось инициализировать эволюцию")
            return False

        self.db.mark_db_initialized(emulator_id)

        # ШАГ 2: Первичное сканирование уровней (только основные разделы)
        scan_ok = self._perform_initial_scan()

        if scan_ok:
            self.db.mark_scan_complete(emulator_id)
            return True
        else:
            logger.error(f"[{self.emulator_name}] ❌ Первичное сканирование не удалось — "
                        f"сбрасываю инициализацию")
            self.db.reset_initialization(emulator_id)
            return False

    def _perform_initial_scan(self) -> bool:
        """
        Первичное сканирование уровней технологий

        Сканирует ТОЛЬКО основные разделы (INITIAL_SCAN_SECTIONS).
        Отложенные разделы (Поход Войска II, Походный Отряд III)
        сканируются позже — при первом обращении.

        Returns:
            bool: True если сканирование прошло успешно
        """
        emulator_id = self.emulator.get('id', 0)

        logger.info(f"[{self.emulator_name}] 📡 Начинаю первичное сканирование эволюции...")

        # Открыть окно Эволюции
        if not self.upgrade.open_evolution_window(self.emulator):
            logger.error(f"[{self.emulator_name}] ❌ Не удалось открыть окно Эволюции")
            return False

        # Только основные разделы (без отложенных)
        sections = self.db.get_initial_scan_sections(emulator_id)
        logger.info(f"[{self.emulator_name}] 📋 Разделы для сканирования: "
                   f"{len(sections)} (отложено: "
                   f"{len(EvolutionDatabase.DEFERRED_SECTIONS)})")

        success = True

        for section_name in sections:
            logger.info(f"[{self.emulator_name}] 📂 Сканирование: {section_name}")

            # Перейти в раздел
            if not self.upgrade.navigate_to_section(self.emulator, section_name):
                logger.warning(f"[{self.emulator_name}] ⚠️ Не удалось открыть: "
                              f"{section_name}")
                press_key(self.emulator, "ESC")
                time.sleep(1)
                continue

            # Определяем макс. swipe_group для этого раздела
            techs_in_section = self.db.get_techs_by_section(emulator_id,
                                                             section_name)
            max_group = max(t['swipe_group'] for t in techs_in_section) \
                if techs_in_section else 0

            # Получаем конфиг свайпов
            swipe_config = self.db.get_swipe_config(section_name)

            # Сканируем
            scanned = self.upgrade.scan_section_levels(
                self.emulator, section_name, swipe_config, max_group
            )

            # Сопоставляем с БД
            matched = self._match_scanned_to_db(emulator_id, section_name,
                                                 scanned, techs_in_section)

            logger.info(f"[{self.emulator_name}] 📊 {section_name}: "
                       f"сопоставлено {matched}/{len(techs_in_section)} технологий")

            # Обновляем прогресс
            self.db.update_last_scanned_section(emulator_id, section_name)

            # Закрываем раздел
            press_key(self.emulator, "ESC")
            time.sleep(1)

        # Закрываем окно Эволюции
        press_key(self.emulator, "ESC")
        time.sleep(0.5)

        # Статистика
        unscanned = self.db.get_unscanned_techs_count(emulator_id)
        all_sections = self.db.get_unique_sections(emulator_id)
        all_count = sum(len(self.db.get_techs_by_section(emulator_id, s))
                        for s in all_sections)
        scanned_count = all_count - unscanned

        logger.success(f"[{self.emulator_name}] 📡 Первичное сканирование завершено: "
                      f"{scanned_count}/{all_count} технологий распознано "
                      f"(отложенных разделов: {len(EvolutionDatabase.DEFERRED_SECTIONS)})")

        return success

    # ==================== НОВЫЙ МЕТОД: сопоставление сканированного с БД ====================
    # (Вынесен из _perform_initial_scan для переиспользования)

    def _match_scanned_to_db(self, emulator_id: int, section_name: str,
                             scanned: list, techs_in_section: list) -> int:
        """
        Сопоставить отсканированные технологии с записями в БД

        Args:
            emulator_id: ID эмулятора
            section_name: название раздела
            scanned: результат OCR-сканирования
            techs_in_section: записи технологий из БД

        Returns:
            int: количество успешно сопоставленных технологий
        """
        matched = 0

        for scan_result in scanned:
            scan_name = scan_result['name']
            scan_level = scan_result['current_level']

            for tech in techs_in_section:
                db_name_lower = tech['tech_name'].lower().replace(' ', '')
                scan_name_lower = scan_name.lower().replace(' ', '')

                # Точное или частичное совпадение
                if db_name_lower == scan_name_lower or \
                        db_name_lower in scan_name_lower or \
                        scan_name_lower in db_name_lower:
                    self.db.update_tech_level(
                        emulator_id, tech['tech_name'],
                        section_name, scan_level
                    )
                    matched += 1
                    break

                # Нечёткое совпадение (>70%)
                if len(db_name_lower) > 4 and len(scan_name_lower) > 4:
                    common = sum(1 for a, b in zip(db_name_lower,
                                                   scan_name_lower) if a == b)
                    ratio = common / max(len(db_name_lower),
                                         len(scan_name_lower))
                    if ratio > 0.7:
                        self.db.update_tech_level(
                            emulator_id, tech['tech_name'],
                            section_name, scan_level
                        )
                        matched += 1
                        break

        return matched