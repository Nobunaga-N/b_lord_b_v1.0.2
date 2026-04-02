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
import math
from datetime import datetime
from typing import Optional

from functions.base_function import BaseFunction
from functions.research.evolution_database import EvolutionDatabase
from functions.research.evolution_upgrade import EvolutionUpgrade
from utils.logger import logger
from utils.adb_controller import press_key
from datetime import datetime  # может уже быть, не дублировать
from functions.prime_times.ds_schedule import (
    get_current_event, is_safe_to_start,
)
from functions.prime_times.ds_navigator import parse_ds_points
from functions.prime_times.speedup_calculator import (
    calculate_plan, choose_drain_type, calculate_target_minutes,
    MAX_TARGET_HOURS,
)
from functions.prime_times.speedup_applier import drain_speedups
from functions.prime_times.prime_storage import PrimeStorage
from functions.backpack_speedups.backpack_storage import BackpackStorage
from utils.image_recognition import find_image


class ResearchFunction(BaseFunction):
    """
    Главная функция эволюции (исследований)

    Аналог BuildingFunction, но для технологий.
    1 слот исследования на все уровни Лорда.
    """

    def __init__(self, emulator, session_state=None):
        super().__init__(emulator, session_state)
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
        1. Функция заморожена → время разморозки
        2. Нет записей / не завершено сканирование → datetime.min
        3. Слот занят → время завершения
        4. Слот свободен + есть что качать → datetime.now()
        5. Всё прокачано → None

        Returns:
            datetime — когда нужен эмулятор
            None — эмулятор не нужен для эволюции
        """
        from utils.function_freeze_manager import function_freeze_manager

        # 1. Единая проверка заморозки (менеджер = единственный источник)
        if function_freeze_manager.is_frozen(emulator_id, 'research'):
            unfreeze_at = function_freeze_manager.get_unfreeze_time(
                emulator_id, 'research'
            )
            if unfreeze_at:
                logger.debug(
                    f"[Emulator {emulator_id}] 🧊 research заморожена "
                    f"до {unfreeze_at.strftime('%H:%M:%S')}"
                )
                return unfreeze_at
            return None

        db = EvolutionDatabase()

        try:
            # 2. Проверяем состояние инициализации
            if not db.has_evolutions(emulator_id):
                return datetime.min

            if not db.is_scan_complete(emulator_id):
                logger.debug(
                    f"[Emulator {emulator_id}] Сканирование эволюции "
                    f"не завершено — требуется повтор"
                )
                return datetime.min

            # 3. УБРАНО: db.is_evolution_frozen() — больше не нужно!
            #    Менеджер уже проверен выше.

            # 4. Проверить слот (auto-complete если таймер истёк)
            db.check_and_complete_research(emulator_id)

            if db.is_slot_busy(emulator_id):
                finish_time = db.get_nearest_research_finish_time(emulator_id)
                return finish_time

            # 5. Слот свободен — есть что качать?
            if db.has_techs_to_research(emulator_id):
                return datetime.now()

            # 6. Всё прокачано
            return None

        except Exception as e:
            logger.error(
                f"[Emulator {emulator_id}] Ошибка в "
                f"ResearchFunction.get_next_event_time: {e}"
            )
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
        from utils.function_freeze_manager import function_freeze_manager

        if function_freeze_manager.is_frozen(emulator_id, 'research'):
            unfreeze_at = function_freeze_manager.get_unfreeze_time(
                emulator_id, 'research'
            )
            if unfreeze_at:
                logger.debug(
                    f"[{self.emulator_name}] ❄️ Эволюция заморожена "
                    f"до {unfreeze_at.strftime('%H:%M:%S')}"
                )
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

        КОНТРАКТ:
        - return True  → исследование начато ИЛИ ситуация обработана
        - return False → критическая ошибка → автозаморозка через run()
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

            # === ПРАЙМ ТАЙМ (точка А — эволюция) ===
            self._handle_prime_time()
            return True  # ← Успех

        elif status == "no_resources":
            self.db.freeze_evolution(emulator_id, hours=4,
                                     reason="Нехватка ресурсов для эволюции")
            logger.warning(f"[{self.emulator_name}] ❄️ Эволюция заморожена на 4 часа "
                           f"(нехватка ресурсов)")
            # ===== ИЗМЕНЕНИЕ: True, не False! =====
            # Ситуация ОБРАБОТАНА: заморозка через БД уже сделана.
            # Планировщик увидит заморозку и не будет запускать.
            return True

        else:  # "error"
            logger.error(f"[{self.emulator_name}] ❌ Ошибка при исследовании "
                         f"{tech_name}")
            # ===== False → run() автоматически заморозит =====
            # mark_failed() НЕ НУЖЕН — False достаточно.
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

    @staticmethod
    def _normalize_for_matching(text: str) -> str:
        """
        Нормализация текста для сопоставления OCR ↔ БД

        Обрабатывает типичные ошибки OCR:
        - Кириллические lookalikes → Латиница (І→I, Г→I, С→C, и т.д.)
        - Цифра 6 вместо буквы б (С6ор → Сбор)
        - Приведение к нижнему регистру, удаление пробелов
        """
        result = text.lower().replace(' ', '')

        # Кириллические lookalikes → латиница (для римских цифр)
        replacements = {
            'і': 'i',  # Украинская І → латинская i
            'і': 'i',  # Ещё один вариант І
            'г': 'г',  # Оставляем Г как есть (это не I)
        }
        for old, new in replacements.items():
            result = result.replace(old, new)

        # OCR ошибка: цифра 6 вместо буквы б
        # "с6ор" → "сбор"
        result = result.replace('6', 'б')

        return result

    def _match_scanned_to_db(self, emulator_id: int, section_name: str,
                             scanned: list, techs_in_section: list) -> int:
        """
        Сопоставить отсканированные технологии с записями в БД

        Использует поиск ЛУЧШЕГО совпадения (не первого выше порога)
        и трекинг использованных записей для предотвращения дублей.

        Args:
            emulator_id: ID эмулятора
            section_name: название раздела
            scanned: результат OCR-сканирования
            techs_in_section: записи технологий из БД

        Returns:
            int: количество успешно сопоставленных технологий
        """
        matched = 0
        used_tech_ids = set()  # Трекинг уже сопоставленных записей БД

        for scan_result in scanned:
            scan_name = scan_result['name']
            scan_level = scan_result['current_level']
            scan_norm = self._normalize_for_matching(scan_name)

            best_tech = None
            best_ratio = 0.0

            for tech in techs_in_section:
                tech_id = tech['id']
                if tech_id in used_tech_ids:
                    continue

                db_norm = self._normalize_for_matching(tech['tech_name'])

                # Точное совпадение (после нормализации)
                if db_norm == scan_norm:
                    best_tech = tech
                    best_ratio = 1.0
                    break  # Лучше не бывает

                # Вычисляем similarity
                ratio = 0.0

                # Содержание
                if db_norm in scan_norm or scan_norm in db_norm:
                    ratio = min(len(db_norm), len(scan_norm)) / \
                            max(len(db_norm), len(scan_norm)) if db_norm else 0

                # Нечёткое совпадение
                if len(db_norm) > 4 and len(scan_norm) > 4:
                    common = sum(1 for a, b in zip(db_norm, scan_norm) if a == b)
                    fuzzy_ratio = common / max(len(db_norm), len(scan_norm))
                    ratio = max(ratio, fuzzy_ratio)

                if ratio > best_ratio and ratio > 0.7:
                    best_ratio = ratio
                    best_tech = tech

            if best_tech:
                used_tech_ids.add(best_tech['id'])
                self.db.update_tech_level(
                    emulator_id, best_tech['tech_name'],
                    section_name, scan_level
                )
                matched += 1

        return matched

    # ==================== PRIME TIME (ТОЧКА А) ====================
    def _handle_prime_time(self):
        """
        Проверить и выполнить drain ускорений эволюции в ДС.

        Вызывается ПОСЛЕ запуска исследования.
        Бот находится в поместье (research_tech закрывает всё ESC×3).

        ВАЖНО: universal НИКОГДА не тратится на эволюцию.
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        try:
            active_funcs = self.session_state.get('_active_functions', [])
            if 'prime_times' not in active_funcs:
                return

            now = datetime.now()
            event = get_current_event(now)
            if event is None:
                return

            event_key = event['event_key']

            ds = self.session_state.get('prime_times')
            if ds and ds.get('completed') and ds.get('event_key') == event_key:
                return

            prime_st = PrimeStorage()
            if prime_st.is_completed(emu_id, event_key):
                return

            progress = prime_st.get_progress(emu_id, event_key)
            spent = float(progress['spent_minutes']) if progress else 0.0

            if spent <= 0 and not is_safe_to_start(now, min_minutes=5):
                return

            if ds is None or ds.get('event_key') != event_key:
                ds = self._init_prime_session(event, prime_st)
                if ds is None:
                    return

            if ds.get('skip_reason') or ds.get('completed'):
                return

            if ds['drain_type'] != 'evolution':
                return

            logger.info(
                f"[{emu_name}] 🎯 Prime Time (evolution): "
                f"target={ds['target_minutes']} мин, "
                f"spent={ds['spent_minutes']:.0f} мин"
            )
            self._drain_evolution_in_prime(ds, event, prime_st)

        except Exception as e:
            logger.error(f"[{emu_name}] ❌ Ошибка в _handle_prime_time: {e}")

    def _init_prime_session(
            self, event: dict, prime_st: PrimeStorage
    ) -> dict | None:
        """Инициализировать session_state['prime_times'] для эволюции.

        FIX: Если ds_progress уже есть — используем сохранённый
        target_minutes вместо пересчёта из текущих очков.
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name
        event_key = event['event_key']
        ppm = event['points_per_min']

        bp_storage = BackpackStorage()
        inventory = bp_storage.get_inventory(emu_id)
        if not inventory:
            return None

        # has_buildings не влияет на evolution (universal = NEVER)
        drain_type, _ = choose_drain_type(inventory, event['type'], True)
        if drain_type is None:
            self._set_prime_skip(event_key, 'not_enough_speedups', prime_st)
            return self.session_state.get('prime_times')

        # ── FIX: Проверяем ds_progress ДО парсинга очков ──
        progress = prime_st.get_progress(emu_id, event_key)

        if progress and progress['status'] == 'in_progress':
            # ═══ ВОССТАНОВЛЕНИЕ ═══
            target_min = int(progress['target_minutes'])
            spent = float(progress['spent_minutes'])
            target_shell = int(progress.get('target_shell', 2))

            logger.info(
                f"[{emu_name}] 🔄 Восстановлено из ds_progress: "
                f"{spent:.0f}/{target_min} мин (shell {target_shell})"
            )

            ds_points = parse_ds_points(self.emulator)
            if ds_points is None:
                ds_points = {'current': 0, 'shell_1': 0, 'shell_2': 0}
        else:
            # ═══ ПЕРВЫЙ ЗАПУСК ═══
            ds_points = parse_ds_points(self.emulator)
            if ds_points is None:
                from utils.function_freeze_manager import (
                    function_freeze_manager,
                )
                function_freeze_manager.freeze(
                    emu_id, 'prime_times', hours=1,
                    reason="Ошибка парсинга очков ДС",
                )
                return None

            target_shell = 2
            target_min = calculate_target_minutes(
                ds_points['current'], ds_points['shell_2'], ppm
            )
            if target_min > MAX_TARGET_HOURS * 60:
                target_min_1 = calculate_target_minutes(
                    ds_points['current'], ds_points['shell_1'], ppm
                )
                if target_min_1 <= MAX_TARGET_HOURS * 60:
                    target_min = target_min_1
                    target_shell = 1
                else:
                    self._set_prime_skip(
                        event_key, '>65h', prime_st
                    )
                    return self.session_state.get('prime_times')

            if target_min <= 0:
                self._set_prime_completed(event_key, prime_st)
                return self.session_state.get('prime_times')

            spent = 0.0

        ds = {
            'event_type': event['type'],
            'points_per_min': ppm,
            'event_end': event['end'],
            'event_key': event_key,
            'ds_parsed': True,
            'current_points': ds_points['current'],
            'shell_1_points': ds_points['shell_1'],
            'shell_2_points': ds_points['shell_2'],
            'target_minutes': target_min,
            'target_shell': target_shell,
            'spent_minutes': spent,
            'drain_type': drain_type,
            'completed': False,
            'skip_reason': None,
        }
        self.session_state['prime_times'] = ds
        prime_st.save_progress(
            emu_id, event_key, target_min,
            int(spent), target_shell, 'in_progress',
        )
        logger.info(
            f"[{emu_name}] Prime init: drain={drain_type}, "
            f"target={target_min} мин (shell {target_shell})"
        )
        return ds

    def _drain_evolution_in_prime(
            self, ds: dict, event: dict, prime_st: PrimeStorage
    ):
        """
        Цикл drain эволюционных ускорений для ДС.

        Бот в поместье (после research_tech → ESC×3).

        Для каждой итерации:
        1. Открыть эволюцию → найти активную технологию
        2. Кликнуть по ней → кнопка "Ускорение"
        3. drain_speedups()
        4. Если эволюция завершилась → ESC → запустить следующую → continue
        5. Если набрали очки → парсить таймер → ESC × 3 → break

        ✅ FIX #5: Обновляет БД после завершения эволюции
        ✅ FIX #6: Запускает новую эволюцию если слот свободен
        ✅ FIX #10: Передаёт timers в calculate_plan

        ВАЖНО: universal НИКОГДА не тратится на эволюцию
        (обеспечивается speedup_calculator через UNIVERSAL_RULES).
        """
        from functions.prime_times.speedup_applier import _parse_remaining_timer
        from utils.ocr_engine import OCREngine
        from utils.adb_controller import tap

        import os

        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name
        bp_storage = BackpackStorage()
        ocr = OCREngine()

        BASE_DIR = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        speedup_btn_path = os.path.join(
            BASE_DIR, 'data', 'templates', 'prime_times', 'button_speedup.png'
        )

        while ds['spent_minutes'] < ds['target_minutes']:
            # Проверка времени ДС
            if not is_safe_to_start(min_minutes=5):
                if ds['spent_minutes'] <= 0:
                    logger.info(f"[{emu_name}] Prime: мало времени до конца ДС")
                break

            # ═══════════════════════════════════════════
            # ✅ FIX #6: Проверяем/запускаем эволюцию
            # ═══════════════════════════════════════════
            if not self.db.is_slot_busy(emu_id):
                next_tech = self.db.get_next_tech_to_research(emu_id)
                if next_tech is None:
                    logger.info(
                        f"[{emu_name}] Prime: нет технологий для исследования"
                    )
                    break

                tech_name = next_tech['tech_name']
                section_name = next_tech['section_name']
                swipe_config = self.db.get_swipe_config(section_name)
                swipe_group = next_tech.get('swipe_group', 0)

                logger.info(
                    f"[{emu_name}] Prime: запускаем эволюцию "
                    f"{tech_name} ({section_name})"
                )

                # research_tech: открывает эволюцию, ставит, ESC×3
                status, timer_sec = self.upgrade.research_tech(
                    self.emulator,
                    tech_name=tech_name,
                    section_name=section_name,
                    swipe_config=swipe_config,
                    swipe_group=swipe_group,
                )

                if status != 'started':
                    logger.warning(
                        f"[{emu_name}] Prime: не удалось запустить "
                        f"эволюцию {tech_name} (status={status})"
                    )
                    break

                if timer_sec:
                    self.db.start_research(
                        emu_id, tech_name, section_name, timer_sec
                    )
                # Бот в поместье после research_tech (ESC×3 внутри)

            # ═══════════════════════════════════════════
            # Открываем эволюцию и ищем активную технологию
            # (используем существующие методы EvolutionUpgrade)
            # ═══════════════════════════════════════════
            if not self.upgrade.open_evolution_window(self.emulator):
                logger.error(f"[{emu_name}] ❌ Не удалось открыть окно эволюции")
                break

            # Получаем активную технологию из БД
            active_tech = self._get_active_tech(emu_id)
            if active_tech is None:
                logger.error(f"[{emu_name}] ❌ Нет активной эволюции в БД")
                press_key(self.emulator, "ESC")
                time.sleep(0.5)
                break

            section_name = active_tech['section_name']
            tech_name = active_tech['tech_name']
            swipe_group = active_tech.get('swipe_group', 0)

            # Навигация к разделу
            if not self.upgrade.navigate_to_section(self.emulator, section_name):
                logger.error(
                    f"[{emu_name}] ❌ Навигация к разделу {section_name}"
                )
                self._close_evo_windows(3)
                break

            # Свайпы если нужно
            swipe_config = self.db.get_swipe_config(section_name)
            self.upgrade.perform_swipes(
                self.emulator, swipe_config, swipe_group
            )

            # Находим технологию на экране
            tech_coords = self.upgrade.find_tech_on_screen(
                self.emulator, tech_name
            )
            if not tech_coords:
                logger.warning(
                    f"[{emu_name}] ⚠️ Технология {tech_name} не найдена"
                )
                self._close_evo_windows(3)
                break

            # Кликаем по технологии
            tap(self.emulator, x=tech_coords[0], y=tech_coords[1])
            time.sleep(2.0)

            # Кнопка "Ускорение" → окно ускорений
            speedup_btn = find_image(
                self.emulator, speedup_btn_path, threshold=0.8
            )
            if not speedup_btn:
                logger.warning(
                    f"[{emu_name}] Prime: кнопка 'Ускорение' не найдена"
                )
                self._close_evo_windows(4)
                break

            tap(self.emulator, x=speedup_btn[0], y=speedup_btn[1])
            time.sleep(1.5)

            # Парсим таймер
            evo_timer_sec = _parse_remaining_timer(
                self.emulator, ocr, 'evolution'
            )

            if not evo_timer_sec or evo_timer_sec <= 0:
                logger.warning(
                    f"[{emu_name}] Prime: не удалось спарсить таймер эволюции"
                )
                self._close_evo_windows(4)
                break

            evo_timer_min = max(1, math.ceil(evo_timer_sec / 60))
            remaining_ds_min = int(ds['target_minutes'] - ds['spent_minutes'])
            batch_target = min(remaining_ds_min, evo_timer_min)

            logger.info(
                f"[{emu_name}] Prime пачка: эволюция, "
                f"таймер={evo_timer_min}мин, "
                f"осталось ДС={remaining_ds_min}мин, "
                f"batch={batch_target}мин"
            )

            inventory = bp_storage.get_inventory(emu_id)

            # ✅ FIX #10: Передаём timers
            timers = {'evolution': evo_timer_sec}

            plan = calculate_plan(
                inventory=inventory,
                target_minutes=batch_target,
                event_type=ds['event_type'],
                drain_type='evolution',
                has_buildings=True,
                target_shell=ds['target_shell'],
                skip_threshold=True,
                timers=timers,  # ← FIX #10
            )

            if plan.is_skip:
                logger.info(
                    f"[{emu_name}] Prime: план пустой — {plan.skip_reason}"
                )
                self._close_evo_windows(4)
                break

            # Drain
            result = drain_speedups(
                self.emulator, plan, 'evolution', self.session_state
            )

            ds['spent_minutes'] += result.minutes_spent
            prime_st.add_spent_minutes(
                emu_id, event['event_key'], int(result.minutes_spent)
            )
            logger.info(
                f"[{emu_name}] Prime: +{result.minutes_spent:.0f} мин, "
                f"итого {ds['spent_minutes']:.0f}/{ds['target_minutes']}"
            )

            if result.building_completed:
                # Эволюция завершилась
                # (building_completed — это generic поле DrainResult,
                #  означает "процесс завершён", не "здание построено")
                logger.info(f"[{emu_name}] Prime: эволюция завершилась!")

                # ✅ FIX #5: Обновить БД (уровень + освободить слот)
                # finish_time ещё в будущем, но ускорение завершило
                self.db._complete_research(emu_id)

                press_key(self.emulator, "ESC")  # крестик
                time.sleep(0.5)
                self._close_evo_windows(2)
                time.sleep(1.0)
                continue  # → следующая итерация (FIX #6 запустит новую)

            # Не завершилась → закрываем
            self._close_evo_windows(4)
            break

        # Финализация
        if ds['spent_minutes'] >= ds['target_minutes']:
            self._set_prime_completed(event['event_key'], prime_st)

    def _get_active_tech(self, emu_id: int) -> dict | None:
        """Получить активную технологию из evolution_slot."""
        try:
            with self.db.db_lock:
                cursor = self.db.conn.cursor()
                cursor.execute("""
                    SELECT e.tech_name, e.section_name, e.swipe_group
                    FROM evolution_slot es
                    JOIN evolutions e ON es.tech_id = e.id
                    WHERE es.emulator_id = ? AND es.is_busy = 1
                """, (emu_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        'tech_name': row['tech_name'],
                        'section_name': row['section_name'],
                        'swipe_group': row['swipe_group'] if 'swipe_group' in row.keys() else 0,
                    }
        except Exception as e:
            logger.error(f"Ошибка _get_active_tech: {e}")
        return None

    def _close_evo_windows(self, count: int):
        """Закрыть N окон эволюции."""
        for _ in range(count):
            press_key(self.emulator, "ESC")
            time.sleep(0.5)

    def _set_prime_completed(self, event_key: str, prime_st: PrimeStorage):
        emu_id = self.emulator.get('id')
        ds = self.session_state.get('prime_times', {})
        ds['completed'] = True
        ds['event_key'] = event_key
        self.session_state['prime_times'] = ds
        prime_st.mark_completed(emu_id, event_key)
        logger.success(f"[{self.emulator_name}] 🎉 Prime: ДС {event_key} завершён!")

    def _set_prime_skip(self, event_key: str, reason: str, prime_st: PrimeStorage):
        emu_id = self.emulator.get('id')
        ds = self.session_state.get('prime_times', {})
        ds['event_key'] = event_key
        ds['skip_reason'] = reason
        ds['completed'] = False
        self.session_state['prime_times'] = ds
        prime_st.mark_skipped(emu_id, event_key, reason)