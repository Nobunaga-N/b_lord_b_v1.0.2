"""
Настройка и запуск автоохоты на диких существ

Функции:
- Определение состояния окна автоохоты (3 состояния)
- Выбор типа дикого (ресурса)
- Ввод уровня дикого
- Настройка чекбоксов отрядов
- Расчёт и ввод количества попыток
- Запуск автоохоты и обработка диалогов
- Мониторинг хода автоохоты

Версия: 1.0
Дата создания: 2025-03-11
"""

import os
import re
import math
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from utils.adb_controller import tap, press_key, execute_command, get_adb_device
from utils.image_recognition import find_image, get_screenshot
from utils.ocr_engine import OCREngine
from utils.config_manager import load_config
from utils.logger import logger
from functions.wilds.wilds_database import (
    WildsDatabase, ENERGY_PER_ATTACK, SQUAD_NAMES_RU
)

# Базовая директория проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class WildsAutoHunt:
    """
    Настройка и запуск автоохоты на диких существ

    Предусловие: окно автоохоты ОТКРЫТО (заголовок виден)
    """

    # ==================== ШАБЛОНЫ ====================

    TEMPLATES = {
        'btn_start_autohunt': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'btn_start_autohunt.png'
        ),
        'btn_stop_autohunt': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'btn_stop_autohunt.png'
        ),
        'btn_restart': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'btn_restart.png'
        ),
        'btn_confirm': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'btn_confirm.png'
        ),
        'btn_cancel': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'btn_cancel.png'
        ),
        'checkbox_on': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'checkbox_on.png'
        ),
        'checkbox_off': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'checkbox_off.png'
        ),
        # Диалоги после нажатия "Начать Автоохоту"
        'dialog_weak_squad': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'dialog_weak_squad.png'
        ),
        'dialog_higher_level': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'dialog_higher_level.png'
        ),
        'dialog_busy_squad': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'dialog_busy_squad.png'
        ),
        'dialog_no_energy': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'dialog_no_energy.png'
        ),
    }

    THRESHOLD = 0.8

    # ==================== КООРДИНАТЫ ====================

    # Ползунок выбора типа дикого
    COORD_SLIDER_LEFT = (36, 275)       # Кнопка ← (сброс влево)
    COORD_SLIDER_RIGHT = (500, 275)     # Кнопка → (вправо)
    COORD_RESOURCE_FIRST = (273, 275)   # Первый ресурс (Яблоки) после сброса
    COORD_RESOURCE_NEXT = (415, 270)    # Второй видимый ресурс (для Листьев/Грунта/Песка/Мёда)

    # Поле ввода уровня дикого
    COORD_LEVEL_INPUT = (456, 396)
    COORD_OK_BUTTON = (457, 906)

    # Чекбоксы отрядов (X одинаковый, Y разный)
    SQUAD_CHECKBOX_X = 416
    SQUAD_CHECKBOXES_Y = {
        'special': 480,
        'squad_1': 525,
        'squad_2': 568,
        'squad_3': 613,
    }

    # X координата для парсинга названий отрядов
    SQUAD_NAME_X = 119

    # X координата для парсинга энергии (правее силы отряда)
    SQUAD_ENERGY_X = 351

    # Поле ввода количества попыток
    COORD_ATTEMPTS_INPUT = (456, 707)

    # Область для чекбокса (ограниченный поиск вокруг каждого отряда)
    CHECKBOX_SEARCH_WIDTH = 60   # ±30 пикселей от центра
    CHECKBOX_SEARCH_HEIGHT = 30  # ±15 пикселей от центра

    # Маппинг ресурса → действия для выбора на ползунке
    # (кол-во кликов вправо после сброса, координаты клика)
    RESOURCE_SELECTION = {
        'apples': (0, COORD_RESOURCE_FIRST),    # Сразу видно после сброса
        'leaves': (0, (415, 270)),               # Сразу видно после сброса
        'soil':   (1, (415, 270)),               # 1 клик вправо
        'sand':   (2, (415, 270)),               # 2 клика вправо
        'honey':  (3, (415, 270)),               # 3 клика вправо
    }

    # Среднее время одной атаки (туда + обратно), в минутах
    ATTACK_DURATION_MINUTES = 4

    # ==================== ИНИЦИАЛИЗАЦИЯ ====================

    def __init__(self):
        self.db = WildsDatabase()
        self._ocr = None

    @property
    def ocr(self) -> OCREngine:
        if self._ocr is None:
            self._ocr = OCREngine(lang='ru')
        return self._ocr

    # ==================== ОПРЕДЕЛЕНИЕ СОСТОЯНИЯ ====================

    def detect_state(self, emulator: Dict) -> str:
        """
        Определить текущее состояние окна автоохоты

        Предусловие: окно автоохоты открыто

        Returns:
            'restart'  — состояние 1: видна кнопка "Начать Заново"
            'ready'    — состояние 2: видна кнопка "Начать Автоохоту"
            'active'   — состояние 3: видна кнопка "Остановить Автоохоту"
            'unknown'  — не удалось определить
        """
        emu_name = emulator.get('name', '?')

        # Порядок проверки по ТЗ:
        # 1. "Начать Заново"
        if find_image(emulator, self.TEMPLATES['btn_restart'], threshold=self.THRESHOLD):
            logger.info(f"[{emu_name}] 📋 Состояние: RESTART (Начать Заново)")
            return 'restart'

        # 2. "Начать Автоохоту"
        if find_image(emulator, self.TEMPLATES['btn_start_autohunt'], threshold=self.THRESHOLD):
            logger.info(f"[{emu_name}] 📋 Состояние: READY (Начать Автоохоту)")
            return 'ready'

        # 3. "Остановить Автоохоту"
        if find_image(emulator, self.TEMPLATES['btn_stop_autohunt'], threshold=self.THRESHOLD):
            logger.info(f"[{emu_name}] 📋 Состояние: ACTIVE (Остановить Автоохоту)")
            return 'active'

        logger.warning(f"[{emu_name}] ⚠️ Состояние окна автоохоты не определено")
        return 'unknown'

    def transition_to_ready(self, emulator: Dict) -> bool:
        """
        Перевести окно в состояние 'ready' (видна "Начать Автоохоту")

        Если 'restart' → кликнуть "Начать Заново" → проверить 'ready'
        Если уже 'ready' → True
        Если 'active' → False (автоохота в процессе)

        Returns:
            bool: True если окно в состоянии ready
        """
        emu_name = emulator.get('name', '?')
        state = self.detect_state(emulator)

        if state == 'ready':
            return True

        if state == 'restart':
            logger.info(f"[{emu_name}] 🔄 Кликаю 'Начать Заново'...")
            btn = find_image(emulator, self.TEMPLATES['btn_restart'], threshold=self.THRESHOLD)
            if btn:
                tap(emulator, btn[0], btn[1])
                time.sleep(2)

                if self.detect_state(emulator) == 'ready':
                    return True

            logger.error(f"[{emu_name}] ❌ Не удалось перейти в состояние ready")
            return False

        if state == 'active':
            logger.info(f"[{emu_name}] ⚡ Автоохота уже в процессе")
            return False

        return False

    # ==================== ВЫБОР РЕСУРСА ====================

    def select_resource(self, emulator: Dict, resource_key: str) -> bool:
        """
        Выбрать тип дикого (ресурс) на ползунке

        Алгоритм:
        1. Сброс ползунка влево (8 кликов)
        2. Нужное кол-во кликов вправо
        3. Клик по ресурсу

        Args:
            resource_key: 'apples', 'leaves', 'soil', 'sand', 'honey'

        Returns:
            bool: True если ресурс выбран
        """
        emu_name = emulator.get('name', '?')
        selection = self.RESOURCE_SELECTION.get(resource_key)

        if not selection:
            logger.error(f"[{emu_name}] ❌ Неизвестный ресурс: {resource_key}")
            return False

        right_clicks, click_coords = selection

        logger.info(
            f"[{emu_name}] 🎯 Выбор ресурса: "
            f"{resource_key} (→×{right_clicks})"
        )

        # Шаг 1: Сброс влево (8 кликов)
        for _ in range(8):
            tap(emulator, *self.COORD_SLIDER_LEFT)
            time.sleep(0.3)

        time.sleep(0.5)

        # Шаг 2: Клики вправо
        for _ in range(right_clicks):
            tap(emulator, *self.COORD_SLIDER_RIGHT)
            time.sleep(0.5)

        # Шаг 3: Клик по ресурсу
        tap(emulator, *click_coords)
        time.sleep(0.5)

        return True

    # ==================== ВВОД УРОВНЯ ДИКОГО ====================

    def input_wild_level(self, emulator: Dict, level: int) -> bool:
        """
        Ввести уровень дикого существа

        Args:
            level: уровень (1-15)

        Returns:
            bool: True если уровень введён
        """
        emu_name = emulator.get('name', '?')
        level = max(1, min(15, level))

        logger.info(f"[{emu_name}] 📝 Ввод уровня дикого: {level}")

        # Клик на поле ввода
        tap(emulator, *self.COORD_LEVEL_INPUT)
        time.sleep(0.5)

        # Backspace ×3 (очистка)
        self._press_backspace(emulator, count=3)
        time.sleep(0.3)

        # Ввод числа
        self._input_text(emulator, str(level))
        time.sleep(0.3)

        # OK
        tap(emulator, *self.COORD_OK_BUTTON)
        time.sleep(0.5)

        return True

    # ==================== НАСТРОЙКА ОТРЯДОВ ====================

    def setup_squads(
        self,
        emulator: Dict,
        emulator_id: int
    ) -> Tuple[List[str], int]:
        """
        Настроить чекбоксы отрядов и определить минимальный уровень

        Читает настройки из GUI, проверяет какие отряды существуют
        в окне автоохоты, ставит/снимает галочки.

        Args:
            emulator: dict эмулятора
            emulator_id: ID эмулятора

        Returns:
            (enabled_squads, min_level): список включённых отрядов и мин. уровень
            ([], 0) при ошибке
        """
        emu_name = emulator.get('name', f"id:{emulator_id}")

        # Загрузить настройки из GUI
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {}).get(str(emulator_id), {})
        squads_config = emu_settings.get("squads", {})

        # Определить какие отряды должны быть включены и их уровни
        desired_state = {}  # {squad_key: {'enabled': bool, 'level': int}}
        for squad_key in ['special', 'squad_1', 'squad_2', 'squad_3']:
            cfg = squads_config.get(squad_key, {})
            desired_state[squad_key] = {
                'enabled': cfg.get('enabled', squad_key in ('special', 'squad_1')),
                'level': cfg.get('wild_level', 1),
            }

        # Определить какие отряды существуют на экране
        existing_squads = self._detect_existing_squads(emulator)
        logger.info(
            f"[{emu_name}] 👥 Существующие отряды: "
            f"{', '.join(SQUAD_NAMES_RU.get(s, s) for s in existing_squads)}"
        )

        # Настроить чекбоксы
        enabled_squads = []
        levels = []

        for squad_key in ['special', 'squad_1', 'squad_2', 'squad_3']:
            if squad_key not in existing_squads:
                # Отряд не существует — пропускаем
                continue

            should_enable = desired_state[squad_key]['enabled']

            # Проверить текущее состояние галочки
            is_checked = self._is_checkbox_checked(emulator, squad_key)

            if is_checked is None:
                # Не удалось определить — пропускаем
                logger.warning(
                    f"[{emu_name}] ⚠️ Не удалось определить галочку "
                    f"{SQUAD_NAMES_RU.get(squad_key, squad_key)}"
                )
                continue

            # Переключить если нужно
            if should_enable != is_checked:
                y = self.SQUAD_CHECKBOXES_Y[squad_key]
                tap(emulator, self.SQUAD_CHECKBOX_X, y)
                time.sleep(0.5)
                action = "включён" if should_enable else "выключен"
                logger.info(
                    f"[{emu_name}] ☑️ {SQUAD_NAMES_RU.get(squad_key, squad_key)}: "
                    f"{action}"
                )

            if should_enable:
                enabled_squads.append(squad_key)
                levels.append(desired_state[squad_key]['level'])

        if not enabled_squads:
            logger.error(f"[{emu_name}] ❌ Нет включённых отрядов")
            return [], 0

        min_level = min(levels) if levels else 1

        logger.info(
            f"[{emu_name}] ✅ Отряды настроены: "
            f"{len(enabled_squads)} шт, мин. уровень={min_level}"
        )

        return enabled_squads, min_level

    # ==================== РАСЧЁТ И ВВОД ПОПЫТОК ====================

    def calculate_and_input_attempts(
        self,
        emulator: Dict,
        emulator_id: int,
        enabled_squads: List[str]
    ) -> int:
        """
        Спарсить энергию отрядов, рассчитать попытки, ввести число

        Args:
            emulator: dict эмулятора
            emulator_id: ID эмулятора
            enabled_squads: список включённых отрядов

        Returns:
            int: введённое количество попыток (0 при ошибке)
        """
        emu_name = emulator.get('name', f"id:{emulator_id}")

        total_attacks = 0

        for squad_key in enabled_squads:
            energy = self._parse_squad_energy(emulator, squad_key)
            if energy is None:
                logger.warning(
                    f"[{emu_name}] ⚠️ Не удалось спарсить энергию "
                    f"{SQUAD_NAMES_RU.get(squad_key, squad_key)}, "
                    f"считаю 0"
                )
                energy = 0

            attacks = math.floor(energy / ENERGY_PER_ATTACK)
            total_attacks += attacks

            # Сохранить в БД
            self.db.update_squad_energy(emulator_id, squad_key, energy)

            logger.info(
                f"[{emu_name}] 🔋 {SQUAD_NAMES_RU.get(squad_key, squad_key)}: "
                f"энергия={energy}/100, атак={attacks}"
            )

        if total_attacks <= 0:
            logger.error(f"[{emu_name}] ❌ Нет доступных атак (энергии не хватает)")
            return 0

        logger.info(f"[{emu_name}] ⚔️ Всего атак: {total_attacks}")

        # Ввести число попыток
        tap(emulator, *self.COORD_ATTEMPTS_INPUT)
        time.sleep(0.5)
        self._press_backspace(emulator, count=3)
        time.sleep(0.3)
        self._input_text(emulator, str(total_attacks))
        time.sleep(0.3)
        tap(emulator, *self.COORD_OK_BUTTON)
        time.sleep(0.5)

        return total_attacks

    def input_attempts(self, emulator: Dict, attempts: int) -> bool:
        """
        Ввести произвольное кол-во попыток в поле ввода

        Используется оркестратором (WildsFunction) когда кол-во
        попыток уже рассчитано заранее (из hunt_plan).

        В отличие от calculate_and_input_attempts(), НЕ парсит энергию
        и НЕ считает попытки — просто вводит переданное число.

        Args:
            emulator: dict эмулятора
            attempts: число попыток для ввода

        Returns:
            bool: True если число введено
        """
        emu_name = emulator.get('name', '?')

        logger.info(f"[{emu_name}] 📝 Ввод попыток: {attempts}")

        # Клик на поле ввода
        tap(emulator, *self.COORD_ATTEMPTS_INPUT)
        time.sleep(0.5)

        # Очистка
        self._press_backspace(emulator, count=3)
        time.sleep(0.3)

        # Ввод числа
        self._input_text(emulator, str(attempts))
        time.sleep(0.3)

        # ОК
        tap(emulator, *self.COORD_OK_BUTTON)
        time.sleep(0.5)

        return True

    # ==================== ЗАПУСК АВТООХОТЫ ====================

    def start_autohunt(self, emulator: Dict) -> str:
        """
        Нажать "Начать Автоохоту" и обработать диалоги

        Returns:
            'success'      — автоохота началась (видна "Остановить")
            'busy_squad'   — занятый отряд (нужно подождать и повторить)
            'no_energy'    — недостаточно энергии
            'failed'       — не удалось запустить
        """
        emu_name = emulator.get('name', '?')

        # Клик "Начать Автоохоту"
        btn = find_image(
            emulator, self.TEMPLATES['btn_start_autohunt'],
            threshold=self.THRESHOLD
        )
        if not btn:
            logger.error(f"[{emu_name}] ❌ Кнопка 'Начать Автоохоту' не найдена")
            return 'failed'

        tap(emulator, btn[0], btn[1])
        time.sleep(2)

        # Проверяем результат (5 вариантов)
        return self._handle_start_result(emulator)

    def _handle_start_result(self, emulator: Dict) -> str:
        """
        Обработать результат после клика "Начать Автоохоту"

        Варианты:
        1. "Остановить Автоохоту" → success
        2. "Не хватает силы" → Подтвердить → проверить
        3. "Можно бить выше уровнем" → Отмена → проверить
        4. "Занятый отряд" → Подтвердить → busy_squad
        5. "Недостаточно энергии" → no_energy
        """
        emu_name = emulator.get('name', '?')

        # 1. Проверяем успех
        if find_image(emulator, self.TEMPLATES['btn_stop_autohunt'], threshold=self.THRESHOLD):
            logger.success(f"[{emu_name}] ✅ Автоохота началась!")
            return 'success'

        # 2. "Не хватает силы для атаки"
        if find_image(emulator, self.TEMPLATES['dialog_weak_squad'], threshold=self.THRESHOLD):
            logger.info(f"[{emu_name}] ⚠️ Диалог: не хватает силы → Подтвердить")
            self._click_confirm(emulator)
            time.sleep(2)
            if find_image(emulator, self.TEMPLATES['btn_stop_autohunt'], threshold=self.THRESHOLD):
                logger.success(f"[{emu_name}] ✅ Автоохота началась (после подтверждения)")
                return 'success'
            return 'failed'

        # 3. "Можно бить существо выше уровнем"
        if find_image(emulator, self.TEMPLATES['dialog_higher_level'], threshold=self.THRESHOLD):
            logger.info(f"[{emu_name}] ⚠️ Диалог: можно бить выше → Отмена")
            self._click_cancel(emulator)
            time.sleep(2)
            if find_image(emulator, self.TEMPLATES['btn_stop_autohunt'], threshold=self.THRESHOLD):
                logger.success(f"[{emu_name}] ✅ Автоохота началась (после отмены)")
                return 'success'
            return 'failed'

        # 4. "Есть занятый отряд"
        if find_image(emulator, self.TEMPLATES['dialog_busy_squad'], threshold=self.THRESHOLD):
            logger.warning(f"[{emu_name}] ⚠️ Диалог: занятый отряд")
            self._click_confirm(emulator)
            return 'busy_squad'

        # 5. "Недостаточно энергии"
        if find_image(emulator, self.TEMPLATES['dialog_no_energy'], threshold=self.THRESHOLD):
            logger.warning(f"[{emu_name}] ⚠️ Диалог: недостаточно энергии")
            press_key(emulator, "ESC")
            return 'no_energy'

        logger.warning(f"[{emu_name}] ⚠️ Неизвестный результат запуска автоохоты")
        return 'failed'

    # ==================== МОНИТОРИНГ ====================

    def check_hunt_progress(self, emulator: Dict) -> Dict:
        """
        Проверить ход автоохоты (вызывается из открытого окна автоохоты)

        Returns:
            dict: {
                'status': 'active' | 'finished' | 'crashed' | 'unknown',
                'remaining_attempts': int or None,
                'estimated_minutes': float or None,
            }
        """
        emu_name = emulator.get('name', '?')

        # Проверяем "Остановить Автоохоту"
        if find_image(emulator, self.TEMPLATES['btn_stop_autohunt'], threshold=self.THRESHOLD):
            remaining = self._parse_remaining_attempts(emulator)
            return {
                'status': 'active',
                'remaining_attempts': remaining,
                'estimated_minutes': None,  # Рассчитается вызывающим кодом
            }

        # Проверяем "Начать Заново"
        if find_image(emulator, self.TEMPLATES['btn_restart'], threshold=self.THRESHOLD):
            remaining = self._parse_remaining_attempts(emulator)
            if remaining is not None and remaining > 0:
                logger.warning(
                    f"[{emu_name}] ⚠️ Автоохота СБИЛАСЬ "
                    f"(осталось {remaining} попыток)"
                )
                return {
                    'status': 'crashed',
                    'remaining_attempts': remaining,
                    'estimated_minutes': None,
                }
            else:
                logger.info(f"[{emu_name}] ✅ Автоохота завершилась успешно")
                return {
                    'status': 'finished',
                    'remaining_attempts': 0,
                    'estimated_minutes': None,
                }

        return {
            'status': 'unknown',
            'remaining_attempts': None,
            'estimated_minutes': None,
        }

    def parse_final_energy(
        self,
        emulator: Dict,
        emulator_id: int,
        enabled_squads: List[str]
    ):
        """
        Спарсить энергию отрядов после завершения автоохоты и записать в БД

        Вызывается при финализации (все ресурсы отработаны)
        """
        emu_name = emulator.get('name', f"id:{emulator_id}")

        # Нужно быть в состоянии ready (после "Начать Заново")
        # чтобы видеть энергию отрядов
        state = self.detect_state(emulator)
        if state == 'restart':
            btn = find_image(emulator, self.TEMPLATES['btn_restart'], threshold=self.THRESHOLD)
            if btn:
                tap(emulator, btn[0], btn[1])
                time.sleep(2)

        for squad_key in enabled_squads:
            energy = self._parse_squad_energy(emulator, squad_key)
            if energy is not None:
                self.db.update_squad_energy(emulator_id, squad_key, energy)
                logger.info(
                    f"[{emu_name}] 🔋 {SQUAD_NAMES_RU.get(squad_key, squad_key)}: "
                    f"энергия={energy}/100 (записано в БД)"
                )

    def monitor_hunt(self, emulator: Dict) -> Dict:
        """
        Проверить текущее состояние активной автоохоты

        Предусловие: окно автоохоты ОТКРЫТО

        Returns:
            {
                'status': 'active' | 'completed' | 'crashed' | 'anomaly' | 'unknown',
                'remaining_attempts': int
            }

        Статусы:
        - active:    видна "Остановить", автоохота идёт
        - completed: видна "Начать Заново", оставшихся попыток == 0
        - crashed:   видна "Начать Заново", оставшихся попыток > 0
        - anomaly:   видна "Начать Автоохоту" (возможен перезапуск эмулятора)
        - unknown:   не удалось определить состояние
        """
        emu_name = emulator.get('name', '?')
        state = self.detect_state(emulator)

        if state == 'active':
            remaining = self._parse_remaining_attempts(emulator)
            logger.info(
                f"[{emu_name}] ✅ Автоохота идёт, "
                f"осталось попыток: {remaining}"
            )
            return {
                'status': 'active',
                'remaining_attempts': remaining if remaining is not None else 0
            }

        if state == 'restart':
            remaining = self._parse_remaining_attempts(emulator)
            if remaining is not None and remaining > 0:
                logger.warning(
                    f"[{emu_name}] ⚠️ Автоохота СБИЛАСЬ, "
                    f"осталось попыток: {remaining}"
                )
                return {
                    'status': 'crashed',
                    'remaining_attempts': remaining
                }
            else:
                logger.info(
                    f"[{emu_name}] ✅ Автоохота ЗАВЕРШИЛАСЬ успешно"
                )
                return {
                    'status': 'completed',
                    'remaining_attempts': 0
                }

        if state == 'ready':
            logger.warning(
                f"[{emu_name}] ⚠️ Аномалия: окно в состоянии ready "
                f"(возможен перезапуск эмулятора)"
            )
            return {
                'status': 'anomaly',
                'remaining_attempts': 0
            }

        logger.error(
            f"[{emu_name}] ❌ Не удалось определить состояние автоохоты"
        )
        return {
            'status': 'unknown',
            'remaining_attempts': 0
        }

    # ==================== ПЕРЕЗАПУСК СБИВШЕЙСЯ ОХОТЫ ====================

    def restart_crashed_hunt(
        self,
        emulator: Dict,
        emulator_id: int,
        resource_key: str,
        level: int,
        enabled_squads: List[str],
        remaining_attempts: int
    ) -> str:
        """
        Перенастроить и перезапустить сбившуюся автоохоту

        Предусловие: окно автоохоты открыто, видна "Начать Заново"

        Алгоритм:
        1. transition_to_ready() (кликнуть "Начать Заново")
        2. Полная настройка: ресурс, уровень, отряды
        3. Ввести оставшееся кол-во попыток
        4. Запустить автоохоту

        Args:
            emulator: dict эмулятора
            emulator_id: ID эмулятора
            resource_key: 'apples', 'leaves', 'soil', 'sand', 'honey'
            level: уровень дикого (1-15)
            enabled_squads: список включённых отрядов
            remaining_attempts: оставшееся кол-во попыток

        Returns:
            'success' | 'busy_squad' | 'no_energy' | 'failed'
        """
        emu_name = emulator.get('name', '?')

        logger.info(
            f"[{emu_name}] 🔄 Перезапуск автоохоты: "
            f"{resource_key}, ур.{level}, попыток={remaining_attempts}"
        )

        # 1. Перейти в состояние ready
        if not self.transition_to_ready(emulator):
            logger.error(f"[{emu_name}] ❌ Не удалось перейти в ready для перезапуска")
            return 'failed'

        # 2. Выбор ресурса
        if not self.select_resource(emulator, resource_key):
            return 'failed'

        # 3. Ввод уровня дикого
        if not self.input_wild_level(emulator, level):
            return 'failed'

        # 4. Настройка отрядов
        self.setup_squads(emulator, emulator_id)

        # 5. Ввод оставшегося кол-ва попыток
        self.input_attempts(emulator, remaining_attempts)

        # 6. Запуск
        result = self.start_autohunt(emulator)

        if result == 'success':
            logger.success(
                f"[{emu_name}] ✅ Автоохота перезапущена: "
                f"{resource_key}, попыток={remaining_attempts}"
            )
        else:
            logger.error(
                f"[{emu_name}] ❌ Перезапуск не удался: {result}"
            )

        return result

    # ==================== ПАРСИНГ ЭНЕРГИИ ОТРЯДОВ ====================

    def parse_all_squad_energy(
        self,
        emulator: Dict,
        emulator_id: int,
        enabled_squads: List[str]
    ) -> Dict[str, int]:
        """
        Спарсить текущую энергию всех включённых отрядов и записать в БД

        Предусловие: окно автоохоты открыто в состоянии ready

        Используется:
        - При финализации (после завершения всех автоохот)
        - При смене ресурса (для расчёта оставшихся атак)
        - При аномалии (для определения доступных атак)

        Args:
            emulator: dict эмулятора
            emulator_id: ID эмулятора
            enabled_squads: список включённых отрядов

        Returns:
            {squad_key: energy} — энергия каждого отряда (0-100)
        """
        emu_name = emulator.get('name', '?')
        result = {}
        total_attacks = 0

        logger.info(
            f"[{emu_name}] 🔋 Парсинг энергии "
            f"({len(enabled_squads)} отрядов)..."
        )

        for squad_key in enabled_squads:
            energy = self._parse_squad_energy(emulator, squad_key)

            if energy is not None:
                self.db.update_squad_energy(emulator_id, squad_key, energy)
                result[squad_key] = energy
                attacks = math.floor(energy / ENERGY_PER_ATTACK)
                total_attacks += attacks
                logger.info(
                    f"[{emu_name}] 🔋 {SQUAD_NAMES_RU.get(squad_key, squad_key)}: "
                    f"энергия={energy}/100, атак={attacks}"
                )
            else:
                logger.warning(
                    f"[{emu_name}] ⚠️ Не удалось спарсить энергию "
                    f"{SQUAD_NAMES_RU.get(squad_key, squad_key)}, считаю 0"
                )
                result[squad_key] = 0

        logger.info(
            f"[{emu_name}] 🔋 Итого: суммарно доступно атак = {total_attacks}"
        )

        return result


    # ==================== ПРИВАТНЫЕ МЕТОДЫ ====================

    def _detect_existing_squads(self, emulator: Dict) -> List[str]:
        """
        Определить какие отряды существуют в окне автоохоты

        Парсит названия отрядов через OCR по известным Y-координатам

        Returns:
            list: ['special', 'squad_1', 'squad_2', 'squad_3'] — только существующие
        """
        existing = []
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            # Если нет скриншота — считаем что есть минимум 2 отряда
            return ['special', 'squad_1']

        # Для каждого отряда проверяем чекбокс в его области
        for squad_key, y in self.SQUAD_CHECKBOXES_Y.items():
            # Область поиска чекбокса
            search_region = (
                self.SQUAD_CHECKBOX_X - self.CHECKBOX_SEARCH_WIDTH // 2,
                y - self.CHECKBOX_SEARCH_HEIGHT // 2,
                self.SQUAD_CHECKBOX_X + self.CHECKBOX_SEARCH_WIDTH // 2,
                y + self.CHECKBOX_SEARCH_HEIGHT // 2,
            )

            # Ищем и включённую и выключенную галочку
            found_on = find_image(
                emulator, self.TEMPLATES['checkbox_on'],
                threshold=self.THRESHOLD
            )
            found_off = find_image(
                emulator, self.TEMPLATES['checkbox_off'],
                threshold=self.THRESHOLD
            )

            # Если хоть один из чекбоксов найден в области — отряд существует
            # Но нам нужен поиск В КОНКРЕТНОЙ ОБЛАСТИ, а find_image ищет по всему экрану
            # Поэтому используем OCR для проверки названия отряда

            # Парсим текст в области названия отряда
            name_region = (
                50,                    # x1 (левее названия)
                y - 15,                # y1
                200,                   # x2 (правее названия)
                y + 15,                # y2
            )

            elements = self.ocr.recognize_text(
                screenshot,
                region=name_region,
                min_confidence=0.3
            )

            text = ' '.join(e.get('text', '') for e in elements).strip()

            if text:
                existing.append(squad_key)
                logger.debug(f"  Отряд {squad_key}: найден текст '{text}'")
            else:
                logger.debug(f"  Отряд {squad_key}: текст не найден (отряд не существует)")
                # Если не нашли текст для squad_2/squad_3 — прекращаем поиск
                if squad_key in ('squad_2', 'squad_3'):
                    break

        # Fallback: если вообще ничего не нашли — считаем минимум 2 отряда
        if not existing:
            existing = ['special', 'squad_1']

        return existing

    def _is_checkbox_checked(self, emulator: Dict, squad_key: str) -> Optional[bool]:
        """
        Проверить состояние галочки конкретного отряда

        Ищет шаблон checkbox_on/checkbox_off в ограниченной области

        Returns:
            True если включена, False если выключена, None если не определено
        """
        y = self.SQUAD_CHECKBOXES_Y.get(squad_key)
        if y is None:
            return None

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        # Вырезаем область вокруг чекбокса
        x1 = max(0, self.SQUAD_CHECKBOX_X - self.CHECKBOX_SEARCH_WIDTH)
        y1 = max(0, y - self.CHECKBOX_SEARCH_HEIGHT)
        x2 = min(540, self.SQUAD_CHECKBOX_X + self.CHECKBOX_SEARCH_WIDTH)
        y2 = min(960, y + self.CHECKBOX_SEARCH_HEIGHT)

        crop = screenshot[y1:y2, x1:x2]

        import cv2
        # Ищем checkbox_on в вырезанной области
        template_on_path = self.TEMPLATES['checkbox_on']
        template_off_path = self.TEMPLATES['checkbox_off']

        score_on = self._match_in_crop(crop, template_on_path)
        score_off = self._match_in_crop(crop, template_off_path)

        if score_on is not None and score_off is not None:
            if score_on > score_off and score_on >= self.THRESHOLD:
                return True
            elif score_off > score_on and score_off >= self.THRESHOLD:
                return False

        if score_on is not None and score_on >= self.THRESHOLD:
            return True
        if score_off is not None and score_off >= self.THRESHOLD:
            return False

        return None

    @staticmethod
    def _match_in_crop(crop, template_path: str) -> Optional[float]:
        """Template matching в вырезанной области"""
        import cv2

        if not os.path.exists(template_path):
            return None

        template = cv2.imread(template_path)
        if template is None:
            return None

        if template.shape[0] > crop.shape[0] or template.shape[1] > crop.shape[1]:
            return None

        result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return max_val

    def _parse_squad_energy(self, emulator: Dict, squad_key: str) -> Optional[int]:
        """
        Спарсить текущую энергию отряда

        Энергия в формате: 178.6K 100/100
        Нужно отфильтровать силу (число с K/M) и взять XX из XX/100

        Returns:
            int: текущая энергия (0-100) или None
        """
        y = self.SQUAD_CHECKBOXES_Y.get(squad_key)
        if y is None:
            return None

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        # Область парсинга: правая часть строки отряда
        region = (280, y - 15, 500, y + 15)

        elements = self.ocr.recognize_text(
            screenshot,
            region=region,
            min_confidence=0.3
        )

        full_text = ' '.join(e.get('text', '') for e in elements)
        logger.debug(f"  Energy OCR ({squad_key}): '{full_text}'")

        # Ищем паттерн: число/100 (энергия)
        # Отфильтровываем силу отряда (число с K или M перед энергией)
        # Правило: всё что после K или M — это энергия
        # Паттерн энергии: XX/100
        energy_pattern = r'(\d+)\s*/\s*100'
        match = re.search(energy_pattern, full_text)

        if match:
            energy = int(match.group(1))
            energy = max(0, min(100, energy))
            return energy

        # Fallback: ищем просто число перед /100
        # Может быть слитно: "178.6K100/100"
        fallback_pattern = r'[KkКкMmМм]\s*(\d+)\s*/\s*100'
        match = re.search(fallback_pattern, full_text)
        if match:
            energy = int(match.group(1))
            return max(0, min(100, energy))

        return None

    def _parse_remaining_attempts(self, emulator: Dict) -> Optional[int]:
        """
        Спарсить "Оставшиеся Попытки:" из окна автоохоты

        Формат: "X раз(а)" по Y ≈ 321

        Returns:
            int: количество оставшихся попыток или None
        """
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        # Область для парсинга оставшихся попыток
        region = (200, 305, 400, 340)

        elements = self.ocr.recognize_text(
            screenshot,
            region=region,
            min_confidence=0.3
        )

        full_text = ' '.join(e.get('text', '') for e in elements)
        logger.debug(f"  Remaining OCR: '{full_text}'")

        # Ищем число
        match = re.search(r'(\d+)', full_text)
        if match:
            return int(match.group(1))

        return None

    # ==================== ADB ХЕЛПЕРЫ ====================

    def _press_backspace(self, emulator: Dict, count: int = 1):
        """Нажать Backspace N раз через ADB keyevent"""
        adb_address = get_adb_device(emulator['port'])
        for _ in range(count):
            execute_command(
                f"adb -s {adb_address} shell input keyevent 67"  # KEYCODE_DEL
            )
            time.sleep(0.1)

    def _input_text(self, emulator: Dict, text: str):
        """Ввести текст через ADB input text"""
        adb_address = get_adb_device(emulator['port'])
        execute_command(
            f"adb -s {adb_address} shell input text {text}"
        )

    def _click_confirm(self, emulator: Dict):
        """Кликнуть кнопку Подтвердить"""
        btn = find_image(
            emulator, self.TEMPLATES['btn_confirm'],
            threshold=self.THRESHOLD
        )
        if btn:
            tap(emulator, btn[0], btn[1])
        time.sleep(1)

    def _click_cancel(self, emulator: Dict):
        """Кликнуть кнопку Отмена"""
        btn = find_image(
            emulator, self.TEMPLATES['btn_cancel'],
            threshold=self.THRESHOLD
        )
        if btn:
            tap(emulator, btn[0], btn[1])
        time.sleep(1)