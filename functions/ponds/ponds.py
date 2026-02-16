"""
Функция пополнения прудов листьями
Периодически загружает листья в 4 пруда через панель навигации

Механика:
- Панель навигации → Ресурсы → Вода → Пруд #N → клик по зданию
- Иконка "Поставка" → кнопка "Доставка" → окно закрывается автоматически
- Повторить для всех 4-х прудов
- После завершения — сброс nav_state для корректной работы следующих функций

Параметры:
- Пруды 7 ур.: вместимость 38000, расход 6120/ч → опустошение ~6.2ч, мин. интервал 2.5ч
- Пруды 8 ур.: вместимость 62000, расход 7560/ч → опустошение ~8.2ч, мин. интервал 4ч

Версия: 1.0
Дата создания: 2025-02-16
"""

import os
import time
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict

from functions.base_function import BaseFunction
from functions.building.navigation_panel import NavigationPanel
from utils.adb_controller import tap, press_key
from utils.image_recognition import find_image
from utils.logger import logger

# Базовая директория проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class PondsFunction(BaseFunction):
    """
    Функция пополнения прудов листьями

    Интервалы пополнения зависят от уровня прудов:
    - Пруды Lv.7: макс 6.2ч (обязательно), мин 2.5ч (можно раньше)
    - Пруды Lv.8+: макс 8.2ч (обязательно), мин 4ч (можно раньше)
    """

    # Количество прудов
    POND_COUNT = 4

    # Координаты
    BUILDING_CENTER = (268, 517)  # Центр здания после "Перейти"

    # Интервалы для разных уровней прудов (в секундах)
    INTERVALS = {
        7: {
            'max': 22320,   # 6.2 часа — обязательное пополнение
            'min': 9000,    # 2.5 часа — минимальный порог "можно заодно"
        },
        8: {
            'max': 29520,   # 8.2 часа — обязательное пополнение
            'min': 14400,   # 4 часа — минимальный порог
        },
    }

    # Шаблоны изображений (ПЛЕЙСХОЛДЕРЫ — заменить на реальные скриншоты)
    TEMPLATES = {
        'supply_icon': os.path.join(BASE_DIR, 'data', 'templates', 'ponds', 'supply_icon.png'),
        'delivery_button': os.path.join(BASE_DIR, 'data', 'templates', 'ponds', 'delivery_button.png'),
    }

    # Пороги распознавания
    THRESHOLD_ICON = 0.8
    THRESHOLD_BUTTON = 0.85

    # БД
    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    def __init__(self, emulator):
        """Инициализация функции пополнения прудов"""
        super().__init__(emulator)
        self.name = "PondsFunction"
        self.panel = NavigationPanel()

        # БД подключение (thread-safe)
        self._db_lock = threading.RLock()
        self._conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_table()

        logger.info(f"[{self.emulator_name}] ✅ PondsFunction инициализирована")

    # ==================== ТАБЛИЦА БД ====================

    def _ensure_table(self):
        """Создать таблицу pond_refills если её нет"""
        with self._db_lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pond_refills (
                    emulator_id INTEGER PRIMARY KEY,
                    last_refill_time TIMESTAMP,
                    pond_level INTEGER DEFAULT 7
                )
            """)
            self._conn.commit()

    # ==================== МЕТОДЫ ДЛЯ ПЛАНИРОВЩИКА ====================

    @staticmethod
    def get_next_event_time(emulator_id: int) -> Optional[datetime]:
        """
        Когда пополнению прудов потребуется эмулятор?

        Лёгкая проверка через БД без запуска эмулятора.
        Вызывается планировщиком для определения времени запуска.

        Логика:
        1. Нет записи в БД → None (ещё не инициализировано)
        2. last_refill_time + max_interval ≤ now → datetime.now() (просрочено!)
        3. last_refill_time + max_interval > now → запланированное время

        Returns:
            datetime — когда нужен эмулятор
            None — не нужен (ещё не инициализировано)
        """
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'data', 'database', 'bot.db'
        )

        try:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Проверяем существует ли таблица
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='pond_refills'
            """)
            if not cursor.fetchone():
                conn.close()
                return None

            cursor.execute("""
                SELECT last_refill_time, pond_level 
                FROM pond_refills 
                WHERE emulator_id = ?
            """, (emulator_id,))

            row = cursor.fetchone()
            conn.close()

            if not row or not row['last_refill_time']:
                return None  # Ещё не инициализировано

            pond_level = row['pond_level'] or 7
            intervals = PondsFunction.INTERVALS.get(pond_level, PondsFunction.INTERVALS[7])

            last_refill = datetime.fromisoformat(row['last_refill_time'])
            deadline = last_refill + timedelta(seconds=intervals['max'])

            now = datetime.now()

            if deadline <= now:
                return now  # Просрочено, нужен немедленно
            else:
                return deadline  # Запланировано

        except Exception as e:
            logger.error(f"PondsFunction.get_next_event_time ошибка: {e}")
            return None

    # ==================== can_execute / execute ====================

    def can_execute(self) -> bool:
        """
        Можно ли выполнить пополнение прудов сейчас?

        Логика:
        - Нет записи → True (первый запуск)
        - now - last_refill ≥ min_interval → True (прошло достаточно, можно "заодно")
        - Иначе → False (слишком рано, пропускаем)
        """
        emulator_id = self.emulator.get('id', 0)

        with self._db_lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                SELECT last_refill_time, pond_level 
                FROM pond_refills 
                WHERE emulator_id = ?
            """, (emulator_id,))

            row = cursor.fetchone()

        # Первый запуск — нет записи
        if not row or not row['last_refill_time']:
            logger.info(f"[{self.emulator_name}] 🆕 Первый запуск пополнения прудов")
            return True

        pond_level = row['pond_level'] or 7
        intervals = self.INTERVALS.get(pond_level, self.INTERVALS[7])

        last_refill = datetime.fromisoformat(row['last_refill_time'])
        elapsed = (datetime.now() - last_refill).total_seconds()

        if elapsed >= intervals['min']:
            minutes_ago = int(elapsed / 60)
            logger.info(f"[{self.emulator_name}] 🌿 Прошло {minutes_ago} мин с пополнения прудов — можно пополнить")
            return True

        remaining = int((intervals['min'] - elapsed) / 60)
        logger.debug(f"[{self.emulator_name}] ⏳ Пруды: рано пополнять, ещё {remaining} мин до мин. порога")
        return False

    def execute(self):
        """
        Пополнить все 4 пруда листьями

        Алгоритм:
        1. Навигация к Пруду #1 через NavigationPanel
        2. Клик по зданию → "Поставка" → "Доставка"
        3. Открыть панель навигации (мы в подвкладке "Вода")
        4. Клик "Перейти" для Пруда #2, повторить
        5. ... для всех 4 прудов
        6. Сбросить nav_state
        7. Обновить last_refill_time в БД
        """
        emulator_id = self.emulator.get('id', 0)

        logger.info(f"[{self.emulator_name}] 🌊 Начинаю пополнение прудов ({self.POND_COUNT} шт)")

        success_count = 0

        for pond_index in range(1, self.POND_COUNT + 1):
            logger.info(f"[{self.emulator_name}] 🌊 Пруд #{pond_index}/{self.POND_COUNT}")

            try:
                if pond_index == 1:
                    # Первый пруд — полная навигация через NavigationPanel
                    if not self._navigate_to_pond(pond_index):
                        logger.error(f"[{self.emulator_name}] ❌ Не удалось перейти к Пруду #{pond_index}")
                        continue
                else:
                    # Последующие пруды — панель уже в подвкладке "Вода"
                    if not self._navigate_to_next_pond(pond_index):
                        logger.error(f"[{self.emulator_name}] ❌ Не удалось перейти к Пруду #{pond_index}")
                        continue

                # Пополнить пруд
                if self._refill_single_pond(pond_index):
                    success_count += 1
                    logger.success(f"[{self.emulator_name}] ✅ Пруд #{pond_index} пополнен")
                else:
                    logger.warning(f"[{self.emulator_name}] ⚠️ Не удалось пополнить Пруд #{pond_index}")

            except Exception as e:
                logger.error(f"[{self.emulator_name}] ❌ Ошибка при пополнении Пруда #{pond_index}: {e}")
                logger.exception(e)

        # Сброс nav_state после завершения (мы в подвкладке "Вода")
        # Чтобы следующая функция (например building) сделала полный ресет навигации
        logger.info(f"[{self.emulator_name}] 🔄 Сброс состояния навигации после пополнения прудов")
        self.panel.nav_state.is_panel_open = False
        self.panel.nav_state.current_tab = None
        self.panel.nav_state.current_section = None
        self.panel.nav_state.current_subsection = None
        self.panel.nav_state.is_collapsed = False
        self.panel.nav_state.is_scrolled_to_top = False

        # Обновляем БД
        self._update_refill_time(emulator_id)

        # Обновляем уровень прудов из таблицы buildings (если есть)
        self._sync_pond_level(emulator_id)

        logger.info(f"[{self.emulator_name}] 🌊 Пополнение прудов завершено: "
                    f"{success_count}/{self.POND_COUNT}")

    # ==================== НАВИГАЦИЯ ====================

    def _navigate_to_pond(self, pond_index: int) -> bool:
        """
        Полная навигация к пруду через NavigationPanel

        Используется для первого пруда — полная навигация
        Ресурсы → Вода → Пруд #N

        Args:
            pond_index: номер пруда (1-4)

        Returns:
            bool: True если успешно перешли к пруду
        """
        logger.debug(f"[{self.emulator_name}] 📍 Навигация к Пруд #{pond_index}")

        # Используем NavigationPanel.navigate_to_building для полной навигации
        success = self.panel.navigate_to_building(
            self.emulator, "Пруд", building_index=pond_index
        )

        if not success:
            logger.error(f"[{self.emulator_name}] ❌ NavigationPanel не смогла перейти к Пруд #{pond_index}")
            return False

        return True

    def _navigate_to_next_pond(self, pond_index: int) -> bool:
        """
        Быстрая навигация к следующему пруду (панель уже в подвкладке "Вода")

        После пополнения предыдущего пруда:
        1. Открыть панель навигации
        2. Мы уже в подвкладке "Вода" — просто кликаем "Перейти" для нужного пруда

        Args:
            pond_index: номер пруда (1-4)

        Returns:
            bool: True если успешно перешли
        """
        logger.debug(f"[{self.emulator_name}] 📍 Быстрая навигация к Пруд #{pond_index}")

        # Открыть панель навигации
        if not self.panel.open_navigation_panel(self.emulator):
            logger.error(f"[{self.emulator_name}] ❌ Не удалось открыть панель навигации")
            return False

        time.sleep(0.5)

        # Панель уже в подвкладке "Вода" — ищем и кликаем нужный пруд
        # Используем внутренний метод NavigationPanel для поиска и клика по зданию
        building_config = self.panel.get_building_config("Пруд")
        if not building_config:
            logger.error(f"[{self.emulator_name}] ❌ Конфиг для Пруд не найден")
            return False

        success = self.panel._find_and_click_building(
            self.emulator, "Пруд", building_config, pond_index
        )

        if not success:
            logger.error(f"[{self.emulator_name}] ❌ Не удалось найти/кликнуть Пруд #{pond_index}")
            return False

        return True

    # ==================== ПОПОЛНЕНИЕ ====================

    def _refill_single_pond(self, pond_index: int) -> bool:
        """
        Пополнить один пруд: клик по зданию → "Поставка" → "Доставка"

        Алгоритм:
        1. Клик по зданию (268, 517) — появляются иконки вокруг
        2. Найти шаблон "Поставка" → клик
        3. Открывается окно с кнопкой "Доставка"
        4. Найти шаблон "Доставка" → клик
        5. Окно закрывается автоматически (ESC не нужен)

        Args:
            pond_index: номер пруда (для логирования)

        Returns:
            bool: True если пополнение успешно
        """
        # Шаг 1: Клик по зданию
        logger.debug(f"[{self.emulator_name}] 🖱️ Клик по зданию Пруд #{pond_index}")
        tap(self.emulator, x=self.BUILDING_CENTER[0], y=self.BUILDING_CENTER[1])
        time.sleep(1.5)  # Ожидание появления иконок вокруг здания

        # Шаг 2: Поиск и клик иконки "Поставка"
        supply_pos = self._find_template_with_retry(
            self.TEMPLATES['supply_icon'],
            self.THRESHOLD_ICON,
            max_retries=3,
            retry_delay=0.5,
            description="Поставка"
        )

        if not supply_pos:
            logger.warning(f"[{self.emulator_name}] ⚠️ Иконка 'Поставка' не найдена для Пруд #{pond_index}")
            # Закрываем иконки через ESC
            press_key(self.emulator, "ESC")
            time.sleep(0.5)
            return False

        logger.debug(f"[{self.emulator_name}] ✅ Иконка 'Поставка' найдена: {supply_pos}")
        tap(self.emulator, x=supply_pos[0], y=supply_pos[1])
        time.sleep(1.5)  # Ожидание открытия окна

        # Шаг 3: Поиск и клик кнопки "Доставка"
        delivery_pos = self._find_template_with_retry(
            self.TEMPLATES['delivery_button'],
            self.THRESHOLD_BUTTON,
            max_retries=3,
            retry_delay=0.5,
            description="Доставка"
        )

        if not delivery_pos:
            logger.warning(f"[{self.emulator_name}] ⚠️ Кнопка 'Доставка' не найдена для Пруд #{pond_index}")
            # Закрываем окно через ESC
            press_key(self.emulator, "ESC")
            time.sleep(0.5)
            return False

        logger.debug(f"[{self.emulator_name}] ✅ Кнопка 'Доставка' найдена: {delivery_pos}")
        tap(self.emulator, x=delivery_pos[0], y=delivery_pos[1])
        time.sleep(1.0)  # Окно закрывается автоматически

        return True

    def _find_template_with_retry(self, template_path: str, threshold: float,
                                   max_retries: int = 3, retry_delay: float = 0.5,
                                   description: str = "") -> Optional[tuple]:
        """
        Поиск шаблона с повторными попытками

        Args:
            template_path: путь к шаблону
            threshold: порог распознавания
            max_retries: максимум попыток
            retry_delay: задержка между попытками
            description: описание для логов

        Returns:
            (x, y) координаты центра или None
        """
        for attempt in range(1, max_retries + 1):
            result = find_image(self.emulator, template_path, threshold=threshold)

            if result:
                return result

            if attempt < max_retries:
                logger.debug(f"[{self.emulator_name}] 🔄 '{description}' не найдена, "
                           f"попытка {attempt}/{max_retries}")
                time.sleep(retry_delay)

        return None

    # ==================== РАБОТА С БД ====================

    def _update_refill_time(self, emulator_id: int):
        """Обновить время последнего пополнения в БД"""
        with self._db_lock:
            cursor = self._conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO pond_refills (emulator_id, last_refill_time, pond_level)
                VALUES (?, ?, 7)
                ON CONFLICT(emulator_id) DO UPDATE SET
                    last_refill_time = excluded.last_refill_time
            """, (emulator_id, now))

            self._conn.commit()
            logger.info(f"[{self.emulator_name}] 💾 Время пополнения прудов обновлено: {now}")

    def _sync_pond_level(self, emulator_id: int):
        """
        Синхронизировать уровень прудов из таблицы buildings

        Берёт минимальный уровень из 4-х прудов.
        Если все ≥ 8 → ставим pond_level = 8 (увеличенные интервалы).
        Иначе → pond_level = 7 (стандартные интервалы).

        Не падает если таблицы buildings нет или прудов нет.
        """
        try:
            with self._db_lock:
                cursor = self._conn.cursor()

                cursor.execute("""
                    SELECT MIN(current_level) as min_level
                    FROM buildings
                    WHERE emulator_id = ? AND building_name = 'Пруд'
                """, (emulator_id,))

                row = cursor.fetchone()

                if row and row['min_level'] is not None:
                    min_level = row['min_level']

                    # Определяем уровень для интервалов
                    # 7 и ниже → параметры для 7, 8 и выше → параметры для 8
                    pond_level = 8 if min_level >= 8 else 7

                    cursor.execute("""
                        UPDATE pond_refills 
                        SET pond_level = ?
                        WHERE emulator_id = ?
                    """, (pond_level, emulator_id))

                    self._conn.commit()

                    logger.debug(f"[{self.emulator_name}] 📊 Уровень прудов: мин={min_level}, "
                               f"параметры для Lv.{pond_level}")

        except Exception as e:
            # Не критично — просто не обновим уровень
            logger.debug(f"[{self.emulator_name}] ⚠️ Не удалось синхронизировать уровень прудов: {e}")