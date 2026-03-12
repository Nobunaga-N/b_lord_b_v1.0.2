"""
Функция: WildsFunction — охота на диких существ

Оркестратор, связывающий все модули:
- WildsNavigation     — навигация город ↔ карта мира ↔ окно автоохоты
- WildsAutoHunt       — настройка, запуск, мониторинг автоохоты
- WildsResourceManager — парсинг складов, планирование охоты
- WildsDatabase       — БД энергии и ресурсов

Два режима работы:
- Режим 1 (hunt_active=False): сбор данных → планирование → первый запуск
- Режим 2 (hunt_active=True):  мониторинг → перезапуск/смена ресурса/финализация

Контракт execute():
- return True  = ситуация обработана (включая заморозку через БД)
- return False = критическая ошибка → автозаморозка через run()

Версия: 1.0
Дата создания: 2025-03-11
"""

import math
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from functions.base_function import BaseFunction
from functions.wilds.wilds_database import (
    WildsDatabase, ENERGY_PER_ATTACK, ENERGY_THRESHOLD,
    WILD_LOOT, SQUAD_NAMES_RU, RESOURCE_NAMES_RU
)
from functions.wilds.wilds_navigation import WildsNavigation
from functions.wilds.wilds_auto_hunt import WildsAutoHunt
from functions.wilds.wilds_resource_manager import WildsResourceManager
from utils.config_manager import load_config
from utils.function_freeze_manager import function_freeze_manager
from utils.logger import logger


class WildsFunction(BaseFunction):
    """
    Оркестратор охоты на диких существ

    Использует session_state['wilds'] для хранения состояния между проходами:
    {
        'hunt_active': bool,
        'hunt_plan': [{'resource': str, 'attempts': int}, ...],
        'current_plan_index': int,
        'wild_level': int,
        'enabled_squads': [str, ...],
        'squads_used': int,
        'estimated_finish': datetime,
        'energy_snapshot': {squad_key: int, ...},
    }
    """

    FUNCTION_NAME = 'wilds'

    # Пауза между типами диких (секунды)
    PAUSE_BETWEEN_RESOURCES = 45

    # Максимальное время одного похода (минуты)
    ATTACK_DURATION_MINUTES = 4

    def __init__(self, emulator, session_state=None):
        super().__init__(emulator, session_state)
        self.name = "WildsFunction"

        # Подмодули (ленивая инициализация)
        self._db = None
        self._navigation = None
        self._auto_hunt = None
        self._resource_manager = None

    # ==================== ЛЕНИВЫЕ СВОЙСТВА ====================

    @property
    def db(self) -> WildsDatabase:
        if self._db is None:
            self._db = WildsDatabase()
        return self._db

    @property
    def navigation(self) -> WildsNavigation:
        if self._navigation is None:
            self._navigation = WildsNavigation()
        return self._navigation

    @property
    def auto_hunt(self) -> WildsAutoHunt:
        if self._auto_hunt is None:
            self._auto_hunt = WildsAutoHunt()
        return self._auto_hunt

    @property
    def resource_manager(self) -> WildsResourceManager:
        if self._resource_manager is None:
            self._resource_manager = WildsResourceManager()
        return self._resource_manager

    # ==================== can_execute ====================

    def can_execute(self):
        """
        Проверить можно ли выполнять функцию сейчас

        Returns:
            True — нужно выполнить execute()
            False — пропускаем (нет энергии / ещё рано / заморожена)
        """
        emu_id = self.emulator.get('id')

        # Заморожена?
        if function_freeze_manager.is_frozen(emu_id, self.FUNCTION_NAME):
            return False

        wilds_state = self.session_state.get('wilds', {})

        # Автоохота активна → проверяем пора ли мониторить
        if wilds_state.get('hunt_active'):
            # Автоохота активна — всегда разрешаем проверку.
            # Таймингом между проходами управляет function_executor
            # через _calculate_sleep_time() и sleep между pass-ами.
            return True

        # Новая охота: проверяем энергию через БД
        # Если данных нет — первый запуск, разрешаем
        if not self.db.has_squad_data(emu_id):
            return True

        return self.db.is_energy_sufficient(emu_id)

    # ==================== execute ====================

    def execute(self):
        """
        Главный метод — два режима работы

        Режим 1 (hunt_active=False): сбор данных → план → запуск
        Режим 2 (hunt_active=True):  мониторинг → действие

        Returns:
            True  — ситуация обработана
            False — критическая ошибка → автозаморозка
        """
        wilds_state = self.session_state.get('wilds', {})

        if wilds_state.get('hunt_active'):
            return self._check_active_hunt()
        else:
            return self._first_launch()

    # ==================== РЕЖИМ 1: ПЕРВЫЙ ЗАПУСК ====================

    def _first_launch(self):
        """
        Полный цикл: парсинг → планирование → запуск первого ресурса

        Returns:
            True — всё обработано (включая случаи когда нет смысла охотиться)
            False — критическая ошибка навигации
        """
        emu_id = self.emulator.get('id')

        # 1. Настройка листа формаций (если нужно)
        if self._should_setup_sheet():
            if not self.navigation.ensure_on_world_map(self.emulator):
                return False
            if not self.navigation.setup_formation_sheet(self.emulator):
                self._freeze_wilds(hours=4, reason="Не удалось настроить лист формаций")
                return True

        # 2. Навигация: карта мира → окно автоохоты
        if not self.navigation.ensure_on_world_map(self.emulator):
            return False

        if not self.navigation.open_autohunt_window(self.emulator):
            return False

        # 3. Привести окно к состоянию ready
        state = self.auto_hunt.detect_state(self.emulator)
        if state == 'active':
            # Автоохота уже идёт (например, запущена вручную) → мониторинг
            logger.info(
                f"[{self.emulator_name}] ⚡ Обнаружена активная автоохота, "
                f"переключаюсь в режим мониторинга"
            )
            return self._adopt_active_hunt()

        if state in ('restart', 'ready'):
            if not self.auto_hunt.transition_to_ready(self.emulator):
                return False
        elif state == 'unknown':
            return False

        # 4. Настройка отрядов и парсинг энергии
        enabled_squads, min_level = self.auto_hunt.setup_squads(
            self.emulator, emu_id
        )

        if not enabled_squads:
            logger.warning(
                f"[{self.emulator_name}] ⚠️ Нет включённых отрядов для охоты"
            )
            self.navigation.close_autohunt_window(self.emulator)
            self.navigation.ensure_in_estate(self.emulator)
            return True

        # 5. Парсинг энергии и расчёт доступных атак
        energy_data = self.auto_hunt.parse_all_squad_energy(
            self.emulator, emu_id, enabled_squads
        )
        total_attacks = sum(
            math.floor(e / ENERGY_PER_ATTACK) for e in energy_data.values()
        )

        if total_attacks <= 0:
            logger.info(
                f"[{self.emulator_name}] ⚡ Недостаточно энергии для охоты"
            )
            self.navigation.close_autohunt_window(self.emulator)
            self.navigation.ensure_in_estate(self.emulator)
            return True

        # 6. Закрыть автоохоту → вернуться в поместье → спарсить склады
        self.navigation.close_autohunt_window(self.emulator)
        if not self.navigation.ensure_in_estate(self.emulator):
            return False

        hunt_plan = self.resource_manager.build_hunt_plan(
            self.emulator, emu_id, total_attacks, min_level
        )

        if not hunt_plan:
            logger.info(
                f"[{self.emulator_name}] 📋 Нет ресурсов для охоты — "
                f"склады полные или все ресурсы выключены"
            )
            return True

        # 7. Сохранить план в session_state
        self.session_state['wilds'] = {
            'hunt_active': False,
            'hunt_plan': hunt_plan,
            'current_plan_index': 0,
            'wild_level': min_level,
            'enabled_squads': enabled_squads,
            'squads_used': len(enabled_squads),
            'estimated_finish': None,
            'energy_snapshot': dict(energy_data),
        }

        # 8. Запуск первого ресурса из плана
        return self._start_hunt_for_resource(hunt_plan[0])

    # ==================== РЕЖИМ 2: МОНИТОРИНГ ====================

    def _check_active_hunt(self):
        """
        Проверка активной автоохоты

        Returns:
            True — обработано
            False — критическая ошибка навигации
        """
        wilds_state = self.session_state.get('wilds', {})

        # 1. Навигация → окно автоохоты
        if not self.navigation.ensure_on_world_map(self.emulator):
            return False

        if not self.navigation.open_autohunt_window(self.emulator):
            return False

        # 2. Проверка состояния
        result = self.auto_hunt.monitor_hunt(self.emulator)
        status = result['status']
        remaining = result['remaining_attempts']

        # --- ACTIVE: автоохота идёт ---
        if status == 'active':
            return self._handle_active(remaining)

        # --- CRASHED: автоохота сбилась ---
        if status == 'crashed':
            return self._handle_crashed(remaining)

        # --- COMPLETED: автоохота завершилась ---
        if status == 'completed':
            return self._handle_completed()

        # --- ANOMALY: ready без restart (перезапуск эмулятора?) ---
        if status == 'anomaly':
            return self._handle_anomaly()

        # --- UNKNOWN ---
        logger.error(
            f"[{self.emulator_name}] ❌ Не удалось определить "
            f"состояние автоохоты"
        )
        return False

    # ==================== ОБРАБОТЧИКИ СОСТОЯНИЙ ====================

    def _handle_active(self, remaining):
        """
        Автоохота идёт — обновить таймер, вернуться в поместье.

        Args:
            remaining: int — кол-во оставшихся попыток,
                       None — если OCR не смог спарсить

        Returns:
            True всегда (ситуация обработана)
        """
        wilds_state = self.session_state['wilds']
        squads_used = wilds_state.get('squads_used', 1)

        if remaining is not None and remaining > 0:
            # Успешно спарсили, есть попытки — пересчитываем таймер
            rounds = math.ceil(remaining / squads_used) if squads_used > 0 else remaining
            finish = datetime.now() + timedelta(
                minutes=rounds * self.ATTACK_DURATION_MINUTES
            )
            wilds_state['estimated_finish'] = finish

            logger.info(
                f"[{self.emulator_name}] ⏳ Автоохота идёт: "
                f"осталось {remaining} попыток, "
                f"завершение ~{finish.strftime('%H:%M:%S')}"
            )

        elif remaining == 0:
            # 0 попыток но кнопка "Остановить" ещё видна —
            # отряды возвращаются, скоро появится "Начать Заново"
            wilds_state['estimated_finish'] = (
                    datetime.now() + timedelta(seconds=60)
            )
            logger.info(
                f"[{self.emulator_name}] ⏳ Автоохота идёт: "
                f"0 попыток осталось, скоро завершится"
            )

        else:
            # None — OCR не смог спарсить попытки.
            # НЕ трогаем estimated_finish — оставляем предыдущий таймер,
            # чтобы function_executor корректно рассчитал sleep.
            logger.warning(
                f"[{self.emulator_name}] ⚠️ Не удалось спарсить "
                f"оставшиеся попытки, сохраняю предыдущий таймер"
            )

        # Пересчитать таймер от МОМЕНТА ПРОВЕРКИ
        self._set_next_check()

        self.navigation.close_autohunt_window(self.emulator)
        self.navigation.ensure_in_estate(self.emulator)
        return True

    def _handle_crashed(self, remaining: int):
        """Автоохота сбилась — перезапуск с оставшимися попытками"""
        wilds_state = self.session_state['wilds']
        plan = wilds_state.get('hunt_plan', [])
        idx = wilds_state.get('current_plan_index', 0)

        if idx >= len(plan):
            return self._finalize()

        current = plan[idx]
        resource_key = current['resource']

        logger.warning(
            f"[{self.emulator_name}] 🔄 Перезапуск автоохоты на "
            f"{RESOURCE_NAMES_RU.get(resource_key, resource_key)}: "
            f"осталось {remaining} попыток"
        )

        result = self.auto_hunt.restart_crashed_hunt(
            self.emulator,
            self.emulator.get('id'),
            resource_key,
            wilds_state.get('wild_level', 1),
            wilds_state.get('enabled_squads', []),
            remaining
        )

        if result == 'success':
            squads_used = wilds_state.get('squads_used', 1)
            rounds = math.ceil(remaining / squads_used) if squads_used > 0 else remaining
            wilds_state['estimated_finish'] = (
                datetime.now() + timedelta(minutes=rounds * self.ATTACK_DURATION_MINUTES)
            )
            self._set_next_check()  # Таймер от момента перезапуска
            self.navigation.close_autohunt_window(self.emulator)
            self.navigation.ensure_in_estate(self.emulator)
            return True

        if result == 'busy_squad':
            # По ТЗ: подождать 2 мин, перенастроить, если опять — freeze 4ч
            # start_autohunt уже обработал первый busy_squad (подтвердить + ждать)
            # Если мы сюда попали — это повторный busy
            self._freeze_wilds(hours=4, reason="Повторный занятый отряд при перезапуске")
            self.navigation.close_autohunt_window(self.emulator)
            self.navigation.ensure_in_estate(self.emulator)
            return True

        if result == 'no_energy':
            return self._finalize()

        # failed
        return False

    def _handle_completed(self):
        """Автоохота завершилась — смена ресурса или финализация"""
        wilds_state = self.session_state['wilds']
        plan = wilds_state.get('hunt_plan', [])
        idx = wilds_state.get('current_plan_index', 0)

        current_resource = plan[idx]['resource'] if idx < len(plan) else '?'
        logger.info(
            f"[{self.emulator_name}] ✅ Автоохота на "
            f"{RESOURCE_NAMES_RU.get(current_resource, current_resource)} "
            f"завершена"
        )

        # Кликнуть "Начать Заново" (сброс окна)
        self.auto_hunt.transition_to_ready(self.emulator)

        # Переходим к смене ресурса
        return self._handle_resource_switch()

    def _handle_anomaly(self):
        """
        Аномалия: окно в состоянии ready (возможен перезапуск эмулятора)

        Решение: парсим энергию из текущего состояния,
        пересчитываем доступные атаки, запускаем заново
        """
        wilds_state = self.session_state.get('wilds', {})
        emu_id = self.emulator.get('id')
        enabled_squads = wilds_state.get('enabled_squads', [])

        if not enabled_squads:
            # Нет данных — считаем что пора финализировать
            return self._finalize()

        logger.info(
            f"[{self.emulator_name}] 🔧 Обработка аномалии: "
            f"парсинг энергии и перезапуск"
        )

        # Парсим энергию
        energy_data = self.auto_hunt.parse_all_squad_energy(
            self.emulator, emu_id, enabled_squads
        )
        total_attacks = sum(
            math.floor(e / ENERGY_PER_ATTACK) for e in energy_data.values()
        )

        if total_attacks <= 0:
            return self._finalize()

        # Закрыть → поместье → перестроить план
        self.navigation.close_autohunt_window(self.emulator)
        if not self.navigation.ensure_in_estate(self.emulator):
            return False

        wild_level = wilds_state.get('wild_level', 1)
        hunt_plan = self.resource_manager.build_hunt_plan(
            self.emulator, emu_id, total_attacks, wild_level
        )

        if not hunt_plan:
            return True

        # Обновить session_state
        wilds_state['hunt_plan'] = hunt_plan
        wilds_state['current_plan_index'] = 0
        wilds_state['energy_snapshot'] = dict(energy_data)

        return self._start_hunt_for_resource(hunt_plan[0])

    # ==================== СМЕНА РЕСУРСА ====================

    def _handle_resource_switch(self):
        """
        Смена ресурса: парсинг складов → перепланирование → запуск

        Вызывается когда текущий ресурс отработан

        Returns:
            True — обработано
            False — критическая ошибка
        """
        wilds_state = self.session_state['wilds']
        emu_id = self.emulator.get('id')

        # 1. Закрыть окно → вернуться в поместье
        self.navigation.close_autohunt_window(self.emulator)
        if not self.navigation.ensure_in_estate(self.emulator):
            return False

        # 2. Рассчитать оставшуюся энергию из snapshot
        remaining_attacks = self._calculate_remaining_attacks()

        if remaining_attacks <= 0:
            logger.info(
                f"[{self.emulator_name}] 🔋 Энергия исчерпана, финализация"
            )
            return self._finalize()

        # 3. Перепарсить склады и построить новый план
        wild_level = wilds_state.get('wild_level', 1)
        hunt_plan = self.resource_manager.build_hunt_plan(
            self.emulator, emu_id, remaining_attacks, wild_level
        )

        if not hunt_plan:
            logger.info(
                f"[{self.emulator_name}] 📋 Все склады полные, финализация"
            )
            return self._finalize()

        # 4. Пауза 1.5 мин (ожидание возврата отрядов)
        logger.info(
            f"[{self.emulator_name}] ⏸ Пауза {self.PAUSE_BETWEEN_RESOURCES}с "
            f"перед охотой на следующий ресурс..."
        )
        time.sleep(self.PAUSE_BETWEEN_RESOURCES)

        # 5. Обновить план в session_state
        wilds_state['hunt_plan'] = hunt_plan
        wilds_state['current_plan_index'] = 0

        # 6. Запуск следующего ресурса
        return self._start_hunt_for_resource(hunt_plan[0])

    # ==================== ЗАПУСК ОХОТЫ НА РЕСУРС ====================

    def _start_hunt_for_resource(self, plan_entry: Dict) -> bool:
        """
        Настроить и запустить автоохоту на конкретный ресурс

        Args:
            plan_entry: {'resource': 'sand', 'attempts': 8}

        Returns:
            True — обработано
            False — критическая ошибка навигации
        """
        wilds_state = self.session_state['wilds']
        emu_id = self.emulator.get('id')
        resource_key = plan_entry['resource']
        attempts = plan_entry['attempts']
        wild_level = wilds_state.get('wild_level', 1)
        enabled_squads = wilds_state.get('enabled_squads', [])
        squads_used = wilds_state.get('squads_used', 1)

        res_name = RESOURCE_NAMES_RU.get(resource_key, resource_key)
        logger.info(
            f"[{self.emulator_name}] 🎯 Запуск охоты: "
            f"{res_name}, ур.{wild_level}, попыток={attempts}"
        )

        # 1. Навигация → окно автоохоты
        if not self.navigation.ensure_on_world_map(self.emulator):
            return False

        if not self.navigation.open_autohunt_window(self.emulator):
            return False

        # 2. Привести в состояние ready
        if not self.auto_hunt.transition_to_ready(self.emulator):
            return False

        # 3. Настройка: ресурс, уровень, отряды
        if not self.auto_hunt.select_resource(self.emulator, resource_key):
            return False

        if not self.auto_hunt.input_wild_level(self.emulator, wild_level):
            return False

        self.auto_hunt.setup_squads(self.emulator, emu_id)

        # 4. Ввод кол-ва попыток
        self.auto_hunt.input_attempts(self.emulator, attempts)

        # 5. Запуск
        result = self.auto_hunt.start_autohunt(self.emulator)

        if result == 'success':
            # Рассчитать estimated_finish
            rounds = math.ceil(attempts / squads_used) if squads_used > 0 else attempts
            finish = datetime.now() + timedelta(
                minutes=rounds * self.ATTACK_DURATION_MINUTES
            )

            wilds_state['hunt_active'] = True
            wilds_state['estimated_finish'] = finish

            # Обновить energy_snapshot: вычесть потраченное
            self._deduct_energy(attempts)

            logger.success(
                f"[{self.emulator_name}] ✅ Автоохота запущена: "
                f"{res_name}, {attempts} попыток, "
                f"завершение ~{finish.strftime('%H:%M:%S')}"
            )

            # Таймер от МОМЕНТА ЗАПУСКА (а не от конца прохода)
            self._set_next_check()
            self.navigation.close_autohunt_window(self.emulator)
            self.navigation.ensure_in_estate(self.emulator)
            return True

        if result == 'busy_squad':
            self._freeze_wilds(
                hours=4, reason=f"Занятый отряд при запуске на {res_name}"
            )
            self.navigation.close_autohunt_window(self.emulator)
            self.navigation.ensure_in_estate(self.emulator)
            return True

        if result == 'no_energy':
            logger.info(
                f"[{self.emulator_name}] 🔋 Недостаточно энергии, финализация"
            )
            return self._finalize()

        # failed
        logger.error(
            f"[{self.emulator_name}] ❌ Не удалось запустить автоохоту: {result}"
        )
        return False

    # ==================== ФИНАЛИЗАЦИЯ ====================

    def _finalize(self):
        """
        Финализация сессии: парсинг энергии → БД → hunt_active=False

        Returns:
            True всегда (финализация — обработанная ситуация)
        """
        wilds_state = self.session_state.get('wilds', {})
        emu_id = self.emulator.get('id')
        enabled_squads = wilds_state.get('enabled_squads', [])

        logger.info(f"[{self.emulator_name}] 🏁 Финализация охоты на диких")

        # Парсим финальную энергию (нужно быть в окне автоохоты)
        if enabled_squads:
            try:
                # Попробуем открыть окно для парсинга энергии
                if self.navigation.ensure_on_world_map(self.emulator):
                    if self.navigation.open_autohunt_window(self.emulator):
                        # Привести в ready для парсинга
                        self.auto_hunt.transition_to_ready(self.emulator)

                        self.auto_hunt.parse_all_squad_energy(
                            self.emulator, emu_id, enabled_squads
                        )
                        self.navigation.close_autohunt_window(self.emulator)
            except Exception as e:
                logger.warning(
                    f"[{self.emulator_name}] ⚠️ Не удалось спарсить "
                    f"финальную энергию: {e}"
                )

        # Обновить session_state
        wilds_state['hunt_active'] = False
        wilds_state['estimated_finish'] = None
        wilds_state.pop('next_check_at', None)  # Очистить таймер проверки
        self.session_state['wilds'] = wilds_state

        # Вернуться в поместье
        self.navigation.ensure_in_estate(self.emulator)

        logger.info(f"[{self.emulator_name}] 🏁 Охота на диких завершена")
        return True

    # ==================== ADOPT ACTIVE HUNT ====================

    def _adopt_active_hunt(self):
        """
        Подхватить обнаруженную активную автоохоту

        Если бот зашёл впервые и обнаружил что автоохота уже идёт
        (запущена вручную или из предыдущей сессии)
        """
        wilds_state = self.session_state.get('wilds', {})
        emu_id = self.emulator.get('id')

        # Парсим оставшиеся попытки
        remaining = self.auto_hunt._parse_remaining_attempts(self.emulator)
        if remaining is None:
            # Не удалось спарсить — ставим дефолт, чтобы не сбить таймер
            remaining = 10
            logger.warning(
                f"[{self.emulator_name}] ⚠️ Не удалось спарсить попытки "
                f"при подхвате, используем дефолт={remaining}"
            )

        # Загрузить настройки отрядов из GUI
        squad_settings = self._load_squad_settings(emu_id)
        enabled_squads = [
            k for k, v in squad_settings.items() if v.get('enabled', False)
        ]
        squads_used = max(len(enabled_squads), 1)

        # Рассчитать estimated_finish
        rounds = math.ceil(remaining / squads_used) if squads_used > 0 else remaining
        finish = datetime.now() + timedelta(
            minutes=rounds * self.ATTACK_DURATION_MINUTES
        )

        # Определить min_level из настроек
        levels = [
            v.get('wild_level', 1)
            for k, v in squad_settings.items() if v.get('enabled', False)
        ]
        wild_level = min(levels) if levels else 1

        self.session_state['wilds'] = {
            'hunt_active': True,
            'hunt_plan': [{'resource': 'unknown', 'attempts': remaining}],
            'current_plan_index': 0,
            'wild_level': wild_level,
            'enabled_squads': enabled_squads,
            'squads_used': squads_used,
            'estimated_finish': finish,
            'energy_snapshot': {},
        }

        logger.info(
            f"[{self.emulator_name}] ⚡ Подхвачена активная автоохота: "
            f"осталось {remaining} попыток, "
            f"завершение ~{finish.strftime('%H:%M:%S')}"
        )

        self._set_next_check()  # Таймер от момента подхвата
        self.navigation.close_autohunt_window(self.emulator)
        self.navigation.ensure_in_estate(self.emulator)
        return True

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    def _set_next_check(self, seconds: int = None):
        """
        Установить время следующей проверки автоохоты

        Вызывается СРАЗУ после запуска/проверки охоты,
        чтобы таймер не зависел от длительности других функций.

        Args:
            seconds: через сколько секунд проверить.
                     None → рассчитать из estimated_finish
        """
        wilds_state = self.session_state.get('wilds', {})

        if seconds is not None:
            wilds_state['next_check_at'] = (
                    datetime.now() + timedelta(seconds=seconds)
            )
            return

        # Авторасчёт: min(до финиша, 10 мин)
        estimated_finish = wilds_state.get('estimated_finish')
        if estimated_finish:
            remaining = (estimated_finish - datetime.now()).total_seconds()
            sleep = min(remaining, 600)  # MAX_SLEEP_BETWEEN_PASSES
            sleep = max(sleep, 60)
        else:
            sleep = 600

        wilds_state['next_check_at'] = (
                datetime.now() + timedelta(seconds=sleep)
        )

    def _calculate_remaining_attacks(self) -> int:
        """
        Рассчитать оставшиеся атаки из energy_snapshot и плана

        Энергия тратится так:
        - При N попытках и S отрядах, каждый отряд делает ceil(N/S) атак
        - Каждая атака = 10 энергии
        - Отряды атакуют ПАРАЛЛЕЛЬНО
        """
        wilds_state = self.session_state.get('wilds', {})
        snapshot = wilds_state.get('energy_snapshot', {})
        plan = wilds_state.get('hunt_plan', [])
        idx = wilds_state.get('current_plan_index', 0)
        squads_used = wilds_state.get('squads_used', 1)

        if not snapshot:
            return 0

        # Подсчёт энергии потраченной КАЖДЫМ отрядом
        # (все завершённые ресурсы до текущего включительно)
        energy_spent_per_squad = 0
        for i in range(idx + 1):
            if i < len(plan):
                attempts = plan[i]['attempts']
                # Каждый отряд делает ceil(attempts / squads) атак
                attacks_per_squad = math.ceil(attempts / squads_used)
                energy_spent_per_squad += attacks_per_squad * ENERGY_PER_ATTACK

        # Считаем оставшиеся атаки
        total_remaining_attacks = 0
        for squad_key, initial_energy in snapshot.items():
            current_energy = max(0, initial_energy - energy_spent_per_squad)
            total_remaining_attacks += math.floor(current_energy / ENERGY_PER_ATTACK)

        return total_remaining_attacks

    def _deduct_energy(self, attempts: int):
        """
        Вычесть потраченную энергию из snapshot

        При запуске автоохоты каждый отряд потратит:
        ceil(attempts / squads_used) * 10 энергии
        """
        wilds_state = self.session_state.get('wilds', {})
        snapshot = wilds_state.get('energy_snapshot', {})
        squads_used = wilds_state.get('squads_used', 1)

        energy_per_squad = math.ceil(attempts / squads_used) * ENERGY_PER_ATTACK

        for squad_key in snapshot:
            snapshot[squad_key] = max(0, snapshot[squad_key] - energy_per_squad)

    def _should_setup_sheet(self) -> bool:
        """
        Нужна ли настройка листа формаций

        Условия:
        - В GUI включён "Активировать Лист 2" (use_sheet_2)
        - Лорд ≥ 16 (если есть данные о Лорде)
        """
        emu_id = self.emulator.get('id')
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(emu_id)
        settings = emu_settings.get(emu_key, {})

        # Проверяем use_sheet_2 — может быть в wilds или в squads
        wilds = settings.get("wilds", {})
        squads = settings.get("squads", {})

        use_sheet_2 = wilds.get("use_sheet_2", False) or squads.get("use_sheet_2", False)

        if not use_sheet_2:
            return False

        # Проверяем уровень Лорда (если есть в БД строительства)
        try:
            from functions.building.building_database import BuildingDatabase
            building_db = BuildingDatabase()
            lord_level = building_db.get_building_level(emu_id, "Лорд")
            if lord_level is not None and lord_level < 16:
                return False
        except Exception:
            pass  # Нет данных — на всякий случай настраиваем

        return True

    def _freeze_wilds(self, hours: int, reason: str):
        """Заморозить функцию диких и залогировать"""
        emu_id = self.emulator.get('id')

        function_freeze_manager.freeze(
            emulator_id=emu_id,
            function_name=self.FUNCTION_NAME,
            hours=hours,
            reason=reason
        )
        logger.warning(
            f"[{self.emulator_name}] 🧊 Дикие заморожены на {hours}ч: {reason}"
        )

    @staticmethod
    def _load_squad_settings(emulator_id: int) -> Dict:
        """
        Загрузить настройки отрядов из gui_config.yaml

        Returns:
            {squad_key: {'enabled': bool, 'wild_level': int}}
        """
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(emulator_id)
        settings = emu_settings.get(emu_key, {})
        squads = settings.get("squads", {})

        result = {}
        defaults = {
            'special': {'enabled': True, 'wild_level': 1},
            'squad_1': {'enabled': True, 'wild_level': 1},
            'squad_2': {'enabled': False, 'wild_level': 1},
            'squad_3': {'enabled': False, 'wild_level': 1},
        }

        for squad_key, default in defaults.items():
            squad_data = squads.get(squad_key, default)
            result[squad_key] = {
                'enabled': squad_data.get('enabled', default['enabled']),
                'wild_level': squad_data.get('wild_level', default['wild_level']),
            }

        return result

    # ==================== ПЛАНИРОВЩИК ====================

    @staticmethod
    def get_next_event_time(emulator_id: int):
        """
        Когда эмулятору нужно запуститься для охоты на диких?

        Используется планировщиком для определения очереди.

        Returns:
            datetime — когда запускать
            None — функция полностью выключена
        """
        # Заморожена?
        if function_freeze_manager.is_frozen(emulator_id, 'wilds'):
            return function_freeze_manager.get_unfreeze_time(
                emulator_id, 'wilds'
            )

        # Проверяем включена ли функция
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        functions = gui_config.get("functions", {})
        if not functions.get("wilds", False):
            return None

        db = WildsDatabase()

        # Нет данных → первый запуск → немедленно
        if not db.has_squad_data(emulator_id):
            return datetime.min

        # Когда энергия восстановится до порога?
        return db.get_estimated_full_energy_time(emulator_id)