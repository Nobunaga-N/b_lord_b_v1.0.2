"""
Функция: BackpackSpeedupsFunction — парсинг ускорений из рюкзака

Сервисная функция. Наследуется от BaseFunction.
НИКОГДА не триггерит запуск эмулятора самостоятельно.

Навигация (из поместья):
  1. tap(43, 920) — открыть рюкзак
  2. tap(163, 90) — вкладка "Ускорение"
  3. Скриншот → парсинг → сохранение в БД
  4. ESC — закрыть рюкзак

Триггеры:
  - Первичная инициализация: нет данных в БД → сканируем
    (при любом запуске эмулятора, не привязано к wilds)
  - Сервисное при автоохоте: 1 раз в сессию, когда wilds hunt_active=True

Контракт execute():
  return True  = обработано (включая неудачный парсинг — не критично)
  return False = критическая ошибка → автозаморозка

Версия: 1.0
"""

import time
from datetime import datetime
from typing import Dict, Optional

from functions.base_function import BaseFunction
from functions.backpack_speedups.backpack_parser import (
    parse_backpack_speedups, DENOM_SECONDS
)
from functions.backpack_speedups.backpack_storage import BackpackStorage

from utils.adb_controller import tap, press_key
from utils.image_recognition import get_screenshot
from utils.ocr_engine import OCREngine
from utils.config_manager import load_config
from utils.logger import logger


# Координаты навигации (540×960)
COORD_OPEN_BACKPACK = (43, 920)       # Кнопка рюкзака из поместья
COORD_SPEEDUP_TAB = (163, 90)        # Вкладка "Ускорение" внутри рюкзака

# Тайминги
DELAY_AFTER_OPEN = 1.5
DELAY_AFTER_TAB = 1.0
DELAY_AFTER_CLOSE = 0.5


class BackpackSpeedupsFunction(BaseFunction):
    """
    Сервисная функция парсинга ускорений из рюкзака

    Аналогична FeedingZoneFunction:
    - get_next_event_time() → None (не триггерит запуск)
    - can_execute() проверяет контекст и флаги
    - execute() делает парсинг
    - Зарегистрирована в FUNCTION_ORDER и FUNCTION_CLASSES
    """

    FUNCTION_NAME = 'backpack_speedups'

    def __init__(self, emulator, session_state=None):
        super().__init__(emulator, session_state)
        self.name = "BackpackSpeedupsFunction"

        self._storage = None
        self._ocr = None

    # ==================== ЛЕНИВЫЕ СВОЙСТВА ====================

    @property
    def storage(self) -> BackpackStorage:
        if self._storage is None:
            self._storage = BackpackStorage()
        return self._storage

    @property
    def ocr(self) -> OCREngine:
        if self._ocr is None:
            self._ocr = OCREngine(lang='ru')
        return self._ocr

    # ==================== ПЛАНИРОВЩИК ====================

    @staticmethod
    def get_next_event_time(emulator_id: int) -> Optional[datetime]:
        """
        Сервисная функция — НИКОГДА не триггерит запуск эмулятора.

        Returns:
            None — всегда
        """
        return None

    # ==================== can_execute ====================

    def can_execute(self) -> bool:
        """
        Сервисная функция: запускается при наличии ЛЮБОЙ активной функции.

        Логика:
        1. Уже выполнялась в этой сессии (done) → False
        2. Нет данных в БД (первичная инициализация) → True
        3. wilds активен и hunt_active=True → True (сервисный парсинг)
        4. Иначе → False (не нужно парсить повторно)
        """
        emu_id = self.emulator.get('id')

        # 1. Уже выполнялась?
        bp_state = self.session_state.get('backpack_speedups', {})
        if bp_state.get('done', False):
            return False

        # 2. Первичная инициализация — нет данных в БД
        if not self.storage.has_data(emu_id):
            logger.debug(
                f"[{self.emulator_name}] 🎒 Нет данных об ускорениях — "
                f"первичное сканирование"
            )
            return True

        # 3. wilds активна и охота запущена → сервисный парсинг
        active_funcs = self.session_state.get('_active_functions', [])
        has_wilds = 'wilds' in active_funcs

        if has_wilds:
            wilds_state = self.session_state.get('wilds', {})
            if wilds_state.get('hunt_active', False):
                return True

        # 4. Данные есть, охоты нет → не нужно
        return False

    # ==================== execute ====================

    def execute(self):
        """
        Парсинг ускорений из рюкзака.

        Алгоритм:
        1. Открыть рюкзак (tap 43:920)
        2. Переключить на вкладку "Ускорение" (tap 163:90)
        3. Скриншот → парсинг
        4. Закрыть рюкзак (ESC)
        5. Сохранить в БД

        Предусловие: бот внутри поместья.

        КОНТРАКТ:
        - return True  → спарсили ИЛИ не удалось (не критично)
        - return False → не используем (сервисная функция не должна
                         замораживаться, всегда True)
        """
        emu_id = self.emulator.get('id')
        emu_name = self.emulator_name

        logger.info(f"[{emu_name}] 🎒 Сканирование ускорений из рюкзака...")

        # 1. Открыть рюкзак
        tap(self.emulator, *COORD_OPEN_BACKPACK)
        time.sleep(DELAY_AFTER_OPEN)

        # 2. Переключить на вкладку "Ускорение"
        tap(self.emulator, *COORD_SPEEDUP_TAB)
        time.sleep(DELAY_AFTER_TAB)

        # 3. Скриншот
        screenshot = get_screenshot(self.emulator)
        if screenshot is None:
            logger.warning(f"[{emu_name}] ⚠️ Не удалось получить скриншот рюкзака")
            self._close_backpack()
            self._mark_done()
            return True  # Не критично

        # 4. Парсинг
        parsed = parse_backpack_speedups(screenshot, self.ocr)

        # 5. Закрыть рюкзак
        self._close_backpack()

        # 6. Сохранить результат
        if parsed:
            self.storage.save_inventory(emu_id, parsed)
            self._log_summary(parsed)
        else:
            logger.warning(
                f"[{emu_name}] ⚠️ Рюкзак: ничего не распознано "
                f"(возможно пустой или ошибка шаблонов)"
            )

        self._mark_done()
        return True

    # ==================== НАВИГАЦИЯ ====================

    def _close_backpack(self):
        """Закрыть рюкзак через ESC"""
        press_key(self.emulator, "ESC")
        time.sleep(DELAY_AFTER_CLOSE)

    # ==================== УТИЛИТЫ ====================

    def _mark_done(self):
        """Пометить что парсинг выполнен в этой сессии"""
        self.session_state.setdefault('backpack_speedups', {})['done'] = True

    def _log_summary(self, parsed: Dict[str, Dict[str, int]]):
        """Краткая сводка по ускорениям"""
        total_seconds = 0
        parts = []

        for stype in sorted(parsed.keys()):
            denoms = parsed[stype]
            type_sec = sum(
                DENOM_SECONDS.get(d, 0) * q for d, q in denoms.items()
            )
            total_seconds += type_sec
            hours = type_sec / 3600
            parts.append(f"{stype}={hours:.1f}ч")

        total_hours = total_seconds / 3600
        summary = ', '.join(parts)

        logger.info(
            f"[{self.emulator_name}] 🎒 Ускорения: {summary} "
            f"(всего {total_hours:.1f}ч)"
        )