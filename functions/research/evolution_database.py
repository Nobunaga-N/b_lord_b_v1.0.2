"""
База данных для хранения состояния технологий Эволюции
Управление прокачкой технологий через SQLite

Включает:
- Таблица evolutions (технологии)
- Таблица evolution_slot (1 слот исследования)
- Таблица function_freeze (пофункциональная заморозка — общая для всех функций)

Версия: 1.0
Дата создания: 2025-02-18
"""

import os
import sqlite3
import yaml
import re
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from utils.logger import logger

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class EvolutionDatabase:
    """
    Класс для работы с базой данных эволюции

    Управляет:
    - Уровнями технологий для каждого эмулятора
    - Слотом исследования (1 слот на все уровни Лорда)
    - Заморозкой функции эволюции (независимо от строительства)
    - Логикой выбора следующей технологии для прокачки
    - Первичным сканированием уровней
    """

    # Путь к базе данных (общая БД с остальными функциями)
    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    # Путь к конфигу порядка прокачки
    CONFIG_PATH = os.path.join(BASE_DIR, 'configs', 'evolution_order.yaml')

    def __init__(self):
        """Инициализация подключения к БД"""
        self.db_lock = threading.RLock()

        # Создаем директорию если нет
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        # Подключение к БД
        self.conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

        # Создаем таблицы
        self._create_tables()

        # Загружаем конфиг
        self._config = None

        logger.info("✅ EvolutionDatabase инициализирована")

    def _create_tables(self):
        """Создать таблицы для эволюции и пофункциональной заморозки"""
        with self.db_lock:
            cursor = self.conn.cursor()

            # ===== ТАБЛИЦА ТЕХНОЛОГИЙ =====
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS evolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    tech_name TEXT NOT NULL,
                    section_name TEXT NOT NULL,
                    lord_level INTEGER NOT NULL,
                    current_level INTEGER NOT NULL DEFAULT 0,
                    target_level INTEGER NOT NULL,
                    max_level INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'idle',
                    timer_finish TIMESTAMP,
                    order_index INTEGER NOT NULL,
                    swipe_group INTEGER NOT NULL DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(emulator_id, tech_name, section_name)
                )
            """)

            # ===== ТАБЛИЦА СЛОТА ИССЛЕДОВАНИЯ (1 слот) =====
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS evolution_slot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    is_busy BOOLEAN NOT NULL DEFAULT 0,
                    tech_id INTEGER,
                    finish_time TIMESTAMP,
                    FOREIGN KEY (tech_id) REFERENCES evolutions(id),
                    UNIQUE(emulator_id)
                )
            """)

            # ===== ТАБЛИЦА ПОФУНКЦИОНАЛЬНОЙ ЗАМОРОЗКИ (общая для всех функций) =====
            # Заменяет старую emulator_freeze
            # Позволяет замораживать building и evolution НЕЗАВИСИМО
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS function_freeze (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    function_name TEXT NOT NULL,
                    freeze_until TIMESTAMP NOT NULL,
                    reason TEXT,
                    UNIQUE(emulator_id, function_name)
                )
            """)

            # ===== ТАБЛИЦА СОСТОЯНИЯ ИНИЦИАЛИЗАЦИИ ЭВОЛЮЦИИ =====
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS evolution_init_state (
                    emulator_id INTEGER PRIMARY KEY,
                    db_initialized BOOLEAN NOT NULL DEFAULT 0,
                    scan_complete BOOLEAN NOT NULL DEFAULT 0,
                    last_scanned_section TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Миграция: добавляем колонку scanned если её нет
            try:
                cursor.execute("ALTER TABLE evolutions ADD COLUMN scanned INTEGER DEFAULT 0")
                logger.info("📦 Миграция: добавлена колонка 'scanned' в evolutions")
            except Exception:
                pass  # Колонка уже существует

            # Миграция: если есть данные в старой emulator_freeze — перенести
            self._migrate_old_freeze(cursor)

            self.conn.commit()
            logger.debug("✅ Таблицы эволюции созданы/проверены")

    def _migrate_old_freeze(self, cursor):
        """
        Перенести данные из старой emulator_freeze в function_freeze

        Вызывается один раз при создании таблиц.
        Старые записи переносятся как function_name='building' (обратная совместимость).
        """
        try:
            # Проверяем существует ли старая таблица
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='emulator_freeze'
            """)
            if not cursor.fetchone():
                return  # Старой таблицы нет — ничего мигрировать

            # Проверяем есть ли данные для миграции
            cursor.execute("SELECT COUNT(*) FROM emulator_freeze")
            count = cursor.fetchone()[0]
            if count == 0:
                return

            # Переносим данные
            cursor.execute("""
                INSERT OR IGNORE INTO function_freeze (emulator_id, function_name, freeze_until, reason)
                SELECT emulator_id, 'building', freeze_until, reason
                FROM emulator_freeze
            """)

            migrated = cursor.rowcount
            if migrated > 0:
                logger.info(f"🔄 Миграция заморозки: {migrated} записей перенесено "
                           f"из emulator_freeze → function_freeze")

        except Exception as e:
            logger.debug(f"Миграция заморозки: {e} (нормально при первом запуске)")

    # ===== ЗАГРУЗКА КОНФИГА =====

    def _load_config(self) -> dict:
        """Загрузить конфиг порядка прокачки"""
        if self._config is not None:
            return self._config

        if not os.path.exists(self.CONFIG_PATH):
            logger.error(f"❌ Конфиг не найден: {self.CONFIG_PATH}")
            return {}

        with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        logger.debug(f"✅ Конфиг эволюции загружен: {self.CONFIG_PATH}")
        return self._config

    # ===== ИНИЦИАЛИЗАЦИЯ ТЕХНОЛОГИЙ =====

    def has_evolutions(self, emulator_id: int) -> bool:
        """Есть ли записи технологий для эмулятора в БД"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM evolutions WHERE emulator_id = ?",
                (emulator_id,)
            )
            return cursor.fetchone()[0] > 0

    def initialize_evolutions_for_emulator(self, emulator_id: int) -> bool:
        """
        Инициализировать записи технологий для эмулятора в БД

        Читает evolution_order.yaml и создаёт записи для всех технологий.
        Так же создаёт слот исследования.

        Args:
            emulator_id: ID эмулятора

        Returns:
            bool: True если успешно
        """
        with self.db_lock:
            logger.info(f"🧬 Инициализация эволюции для эмулятора {emulator_id}...")

            cursor = self.conn.cursor()

            # Проверяем, не инициализирован ли уже
            cursor.execute(
                "SELECT COUNT(*) FROM evolutions WHERE emulator_id = ?",
                (emulator_id,)
            )
            if cursor.fetchone()[0] > 0:
                logger.warning(f"⚠️ Эмулятор {emulator_id} уже инициализирован (эволюция)")
                return True

            config = self._load_config()
            if not config:
                logger.error("❌ Не удалось загрузить конфиг эволюции")
                return False

            # Глобальный счётчик порядка (order_index)
            order_index = 0
            techs_created = 0

            # Обходим все уровни лорда
            for lord_key in sorted(config.keys()):
                if not lord_key.startswith('lord_'):
                    continue  # Пропускаем swipe_config и другие ключи

                lord_level = int(lord_key.replace('lord_', ''))
                techs = config[lord_key].get('techs', [])

                for tech in techs:
                    name = tech['name']
                    section = tech['section']
                    target = tech['target_level']
                    max_lvl = tech['max_level']
                    swipe = tech.get('swipe_group', 0)

                    cursor.execute("""
                        INSERT INTO evolutions 
                        (emulator_id, tech_name, section_name, lord_level,
                         current_level, target_level, max_level, status,
                         order_index, swipe_group)
                        VALUES (?, ?, ?, ?, 0, ?, ?, 'idle', ?, ?)
                    """, (emulator_id, name, section, lord_level,
                          target, max_lvl, order_index, swipe))

                    order_index += 1
                    techs_created += 1

            # Создаём слот исследования
            cursor.execute("""
                INSERT OR IGNORE INTO evolution_slot 
                (emulator_id, is_busy, tech_id, finish_time)
                VALUES (?, 0, NULL, NULL)
            """, (emulator_id,))

            self.conn.commit()

            logger.success(f"✅ Инициализировано {techs_created} технологий для эмулятора {emulator_id}")
            return True

    # ===== ПОЛУЧЕНИЕ ТЕХНОЛОГИЙ =====

    def get_tech(self, emulator_id: int, tech_name: str,
                 section_name: str) -> Optional[Dict]:
        """Получить технологию по имени и разделу"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM evolutions 
                WHERE emulator_id = ? AND tech_name = ? AND section_name = ?
            """, (emulator_id, tech_name, section_name))

            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_techs(self, emulator_id: int) -> List[Dict]:
        """Получить все технологии для эмулятора"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM evolutions 
                WHERE emulator_id = ?
                ORDER BY order_index ASC
            """, (emulator_id,))

            return [dict(row) for row in cursor.fetchall()]

    def get_lord_level(self, emulator_id: int) -> int:
        """
        Получить текущий уровень Лорда из таблицы buildings

        Обрабатывает случай когда таблица buildings ещё не создана
        (строительство не инициализировано).

        Returns:
            int: текущий уровень Лорда (по умолчанию 10)
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            try:
                # Проверяем существование таблицы buildings
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='buildings'
                """)
                if not cursor.fetchone():
                    logger.debug("⚠️ Таблица buildings не существует, "
                                "возвращаем уровень Лорда по умолчанию (10)")
                    return 10

                cursor.execute("""
                    SELECT current_level FROM buildings 
                    WHERE emulator_id = ? AND building_name = 'Лорд'
                    LIMIT 1
                """, (emulator_id,))

                row = cursor.fetchone()
                if row:
                    return row['current_level']

            except Exception as e:
                logger.warning(f"⚠️ Ошибка получения уровня Лорда: {e}, "
                              f"возвращаем 10 по умолчанию")

            return 10

    #==================== НОВЫЕ МЕТОДЫ для инициализации ====================

    # Разделы которые сканируются при первичной инициализации
    INITIAL_SCAN_SECTIONS = [
        "Развитие Территории",
        "Базовый Бой",
        "Средний Бой",
        "Особый Отряд",
        "Походный Отряд I",
        "Развитие Района",
        "Эволюция Плотоядных",
        "Эволюция Всеядных",
    ]

    # Разделы которые сканируются позже (когда нужно качать технологии из них)
    DEFERRED_SECTIONS = [
        "Поход Войска II",
        "Походный Отряд III",
    ]

    def mark_db_initialized(self, emulator_id: int):
        """Отметить что записи в БД созданы (ШАГ 1 инициализации)"""
        with self.db_lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO evolution_init_state 
                (emulator_id, db_initialized, scan_complete, updated_at)
                VALUES (?, 1, 0, CURRENT_TIMESTAMP)
            """, (emulator_id,))
            self.conn.commit()

    def is_scan_complete(self, emulator_id: int) -> bool:
        """Проверить завершено ли первичное сканирование"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT scan_complete FROM evolution_init_state 
                WHERE emulator_id = ?
            """, (emulator_id,))
            row = cursor.fetchone()
            return bool(row and row['scan_complete'])

    def mark_scan_complete(self, emulator_id: int):
        """Отметить что первичное сканирование завершено"""
        with self.db_lock:
            self.conn.execute("""
                UPDATE evolution_init_state 
                SET scan_complete = 1, updated_at = CURRENT_TIMESTAMP
                WHERE emulator_id = ?
            """, (emulator_id,))
            self.conn.commit()

    def update_last_scanned_section(self, emulator_id: int, section_name: str):
        """Обновить последний отсканированный раздел (для recovery)"""
        with self.db_lock:
            self.conn.execute("""
                UPDATE evolution_init_state 
                SET last_scanned_section = ?, updated_at = CURRENT_TIMESTAMP
                WHERE emulator_id = ?
            """, (section_name, emulator_id))
            self.conn.commit()

    def reset_initialization(self, emulator_id: int):
        """
        Сбросить инициализацию при неудачном первом запуске

        Удаляет все записи эволюции для эмулятора и состояние инициализации,
        чтобы следующий запуск начал с нуля.
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM evolutions WHERE emulator_id = ?",
                           (emulator_id,))
            cursor.execute("DELETE FROM evolution_slot WHERE emulator_id = ?",
                           (emulator_id,))
            cursor.execute("DELETE FROM evolution_init_state WHERE emulator_id = ?",
                           (emulator_id,))
            self.conn.commit()
            logger.warning(f"🔄 Инициализация эволюции сброшена для эмулятора {emulator_id}")

    def get_initial_scan_sections(self, emulator_id: int) -> list:
        """
        Получить разделы для ПЕРВИЧНОГО сканирования
        (без отложенных разделов)
        """
        all_sections = self.get_unique_sections(emulator_id)
        return [s for s in all_sections if s not in self.DEFERRED_SECTIONS]

    def needs_deferred_scan(self, emulator_id: int, section_name: str) -> bool:
        """
        Проверить нужно ли отсканировать отложенный раздел

        Возвращает True если:
        - Раздел в списке отложенных
        - Все технологии в разделе имеют current_level == 0 (ещё не сканировались)
        """
        if section_name not in self.DEFERRED_SECTIONS:
            return False

        with self.db_lock:
            cursor = self.conn.cursor()
            # Проверяем есть ли хоть одна отсканированная технология в разделе
            cursor.execute("""
                SELECT COUNT(*) FROM evolutions 
                WHERE emulator_id = ? AND section_name = ?
                  AND (current_level > 0 OR status = 'completed')
            """, (emulator_id, section_name))
            scanned_count = cursor.fetchone()[0]
            return scanned_count == 0

    # ===== ОПРЕДЕЛЕНИЕ СЛЕДУЮЩЕЙ ТЕХНОЛОГИИ =====

    def get_next_tech_to_research(self, emulator_id: int) -> Optional[Dict]:
        """
        Определить следующую технологию для исследования

        Логика:
        1. Получить текущий уровень Лорда
        2. Пройти по всем технологиям В ПОРЯДКЕ order_index
        3. Пропустить технологии с lord_level > текущий уровень Лорда
        4. Пропустить технологии со status='completed' или status='researching'
        5. Найти первую технологию где current_level < target_level

        Returns:
            dict с полями технологии или None если нечего качать
        """
        with self.db_lock:
            lord_level = self.get_lord_level(emulator_id)

            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM evolutions 
                WHERE emulator_id = ? 
                  AND lord_level <= ?
                  AND status != 'researching'
                  AND current_level < target_level
                ORDER BY order_index ASC
                LIMIT 1
            """, (emulator_id, lord_level))

            row = cursor.fetchone()
            if row:
                tech = dict(row)
                logger.debug(f"🎯 Следующая технология: {tech['tech_name']} "
                           f"({tech['section_name']}) "
                           f"Lv.{tech['current_level']}/{tech['target_level']}")
                return tech

            logger.debug(f"✅ Все доступные технологии прокачаны (Лорд Lv.{lord_level})")
            return None

    def has_techs_to_research(self, emulator_id: int) -> bool:
        """Есть ли технологии для исследования"""
        return self.get_next_tech_to_research(emulator_id) is not None

    # ===== СЛОТ ИССЛЕДОВАНИЯ =====

    def is_slot_busy(self, emulator_id: int) -> bool:
        """Занят ли слот исследования"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT is_busy, finish_time FROM evolution_slot 
                WHERE emulator_id = ?
            """, (emulator_id,))

            row = cursor.fetchone()
            if not row:
                return False

            if not row['is_busy']:
                return False

            # Проверяем не истёк ли таймер
            if row['finish_time']:
                finish_time = row['finish_time']
                if isinstance(finish_time, str):
                    finish_time = datetime.fromisoformat(finish_time)
                if datetime.now() >= finish_time:
                    # Таймер истёк — освобождаем слот
                    self._complete_research(emulator_id)
                    return False

            return True

    def get_slot_finish_time(self, emulator_id: int) -> Optional[datetime]:
        """Получить время завершения текущего исследования"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT finish_time FROM evolution_slot 
                WHERE emulator_id = ? AND is_busy = 1
            """, (emulator_id,))

            row = cursor.fetchone()
            if not row or not row['finish_time']:
                return None

            finish_time = row['finish_time']
            if isinstance(finish_time, str):
                finish_time = datetime.fromisoformat(finish_time)

            return finish_time if finish_time > datetime.now() else None

    def start_research(self, emulator_id: int, tech_name: str,
                       section_name: str, timer_seconds: int):
        """
        Начать исследование технологии

        Args:
            emulator_id: ID эмулятора
            tech_name: название технологии
            section_name: раздел
            timer_seconds: время исследования в секундах
        """
        with self.db_lock:
            cursor = self.conn.cursor()

            # Получаем технологию
            tech = self.get_tech(emulator_id, tech_name, section_name)
            if not tech:
                logger.error(f"❌ Технология не найдена: {tech_name} ({section_name})")
                return

            tech_id = tech['id']
            new_level = tech['current_level'] + 1
            finish_time = datetime.now() + timedelta(seconds=timer_seconds)

            # Обновляем технологию
            cursor.execute("""
                UPDATE evolutions 
                SET status = 'researching',
                    timer_finish = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (finish_time, tech_id))

            # Обновляем слот
            cursor.execute("""
                INSERT OR REPLACE INTO evolution_slot 
                (emulator_id, is_busy, tech_id, finish_time)
                VALUES (?, 1, ?, ?)
            """, (emulator_id, tech_id, finish_time))

            self.conn.commit()

            logger.info(f"🧬 Начато исследование: {tech_name} ({section_name}) "
                       f"Lv.{tech['current_level']} → Lv.{new_level}")
            logger.info(f"⏱️ Завершение: {finish_time.strftime('%H:%M:%S')}")

    def _complete_research(self, emulator_id: int):
        """
        Завершить исследование (вызывается автоматически при истечении таймера)
        """
        cursor = self.conn.cursor()

        # Получаем текущий слот
        cursor.execute("""
            SELECT tech_id FROM evolution_slot 
            WHERE emulator_id = ? AND is_busy = 1
        """, (emulator_id,))

        row = cursor.fetchone()
        if not row or not row['tech_id']:
            return

        tech_id = row['tech_id']

        # Получаем технологию
        cursor.execute("SELECT * FROM evolutions WHERE id = ?", (tech_id,))
        tech = cursor.fetchone()
        if not tech:
            return

        new_level = tech['current_level'] + 1
        new_status = 'completed' if new_level >= tech['target_level'] else 'idle'

        # Обновляем технологию
        cursor.execute("""
            UPDATE evolutions 
            SET current_level = ?,
                status = ?,
                timer_finish = NULL,
                last_updated = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_level, new_status, tech_id))

        # Освобождаем слот
        cursor.execute("""
            UPDATE evolution_slot 
            SET is_busy = 0, tech_id = NULL, finish_time = NULL
            WHERE emulator_id = ?
        """, (emulator_id,))

        self.conn.commit()

        logger.success(f"✅ Исследование завершено: {tech['tech_name']} → Lv.{new_level}")

    def check_and_complete_research(self, emulator_id: int) -> bool:
        """
        Проверить и завершить исследование если таймер истёк

        Returns:
            bool: True если исследование было завершено
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT finish_time FROM evolution_slot 
                WHERE emulator_id = ? AND is_busy = 1 AND finish_time IS NOT NULL
            """, (emulator_id,))

            row = cursor.fetchone()
            if not row:
                return False

            finish_time = row['finish_time']
            if isinstance(finish_time, str):
                finish_time = datetime.fromisoformat(finish_time)

            if datetime.now() >= finish_time:
                self._complete_research(emulator_id)
                return True

            return False

    # ===== ОБНОВЛЕНИЕ УРОВНЕЙ (первичное сканирование) =====

    def update_tech_level(self, emulator_id: int, tech_name: str,
                          section_name: str, level: int):
        """
        Обновить текущий уровень технологии (после OCR сканирования)

        Args:
            emulator_id: ID эмулятора
            tech_name: название технологии
            section_name: раздел
            level: текущий уровень (или -1 для MAX)
        """
        with self.db_lock:
            cursor = self.conn.cursor()

            # Если level == -1 → MAX, ставим current_level = target_level
            if level == -1:
                cursor.execute("""
                    UPDATE evolutions 
                    SET current_level = target_level,
                        status = 'completed',
                        scanned = 1,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE emulator_id = ? AND tech_name = ? AND section_name = ?
                """, (emulator_id, tech_name, section_name))
            else:
                # Определяем статус
                tech = self.get_tech(emulator_id, tech_name, section_name)
                if tech:
                    new_status = 'completed' if level >= tech['target_level'] else 'idle'
                else:
                    new_status = 'idle'

                cursor.execute("""
                    UPDATE evolutions 
                    SET current_level = ?,
                        status = ?,
                        scanned = 1,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE emulator_id = ? AND tech_name = ? AND section_name = ?
                """, (level, new_status, emulator_id, tech_name, section_name))

            self.conn.commit()

    def get_techs_by_section(self, emulator_id: int,
                             section_name: str) -> List[Dict]:
        """Получить все технологии раздела"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM evolutions 
                WHERE emulator_id = ? AND section_name = ?
                ORDER BY order_index ASC
            """, (emulator_id, section_name))

            return [dict(row) for row in cursor.fetchall()]

    def get_unique_sections(self, emulator_id: int) -> List[str]:
        """Получить список уникальных разделов"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT DISTINCT section_name FROM evolutions 
                WHERE emulator_id = ?
                ORDER BY order_index ASC
            """, (emulator_id,))

            return [row['section_name'] for row in cursor.fetchall()]

    def get_unscanned_techs_count(self, emulator_id: int) -> int:
        """Количество технологий которые ещё не сканировались"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM evolutions 
                WHERE emulator_id = ? AND scanned = 0
            """, (emulator_id,))
            return cursor.fetchone()[0]

    # ===== ПОФУНКЦИОНАЛЬНАЯ ЗАМОРОЗКА =====
    # Эти методы работают с таблицей function_freeze
    # и могут использоваться ЛЮБОЙ функцией (building, evolution, и т.д.)

    @staticmethod
    def freeze_function(emulator_id: int, function_name: str,
                        hours: int = 4, reason: str = "Нехватка ресурсов",
                        db_path: str = None):
        """
        Заморозить конкретную функцию на эмуляторе

        Args:
            emulator_id: ID эмулятора
            function_name: имя функции ('building', 'evolution', и т.д.)
            hours: часы заморозки
            reason: причина
            db_path: путь к БД (для статических вызовов)
        """
        if db_path is None:
            db_path = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            freeze_until = datetime.now() + timedelta(hours=hours)
            conn.execute("""
                INSERT OR REPLACE INTO function_freeze 
                (emulator_id, function_name, freeze_until, reason)
                VALUES (?, ?, ?, ?)
            """, (emulator_id, function_name, freeze_until, reason))
            conn.commit()
            logger.warning(f"❄️ [{function_name}] Эмулятор {emulator_id} заморожен "
                          f"до {freeze_until.strftime('%H:%M:%S')} ({reason})")
        finally:
            conn.close()

    @staticmethod
    def is_function_frozen(emulator_id: int, function_name: str,
                           db_path: str = None) -> bool:
        """
        Проверить заморожена ли функция на эмуляторе

        Args:
            emulator_id: ID эмулятора
            function_name: имя функции

        Returns:
            bool: True если заморожена
        """
        if db_path is None:
            db_path = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT freeze_until FROM function_freeze 
                WHERE emulator_id = ? AND function_name = ?
            """, (emulator_id, function_name))

            row = cursor.fetchone()
            if not row:
                return False

            freeze_until = row['freeze_until']
            if isinstance(freeze_until, str):
                freeze_until = datetime.fromisoformat(freeze_until)

            if datetime.now() < freeze_until:
                return True
            else:
                # Истекла — удаляем
                cursor.execute("""
                    DELETE FROM function_freeze 
                    WHERE emulator_id = ? AND function_name = ?
                """, (emulator_id, function_name))
                conn.commit()
                return False
        finally:
            conn.close()

    @staticmethod
    def get_function_freeze_until(emulator_id: int, function_name: str,
                                  db_path: str = None) -> Optional[datetime]:
        """
        Время разморозки функции

        Returns:
            datetime или None
        """
        if db_path is None:
            db_path = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT freeze_until FROM function_freeze 
                WHERE emulator_id = ? AND function_name = ?
            """, (emulator_id, function_name))

            row = cursor.fetchone()
            if not row:
                return None

            freeze_until = row['freeze_until']
            if isinstance(freeze_until, str):
                freeze_until = datetime.fromisoformat(freeze_until)

            return freeze_until if freeze_until > datetime.now() else None
        finally:
            conn.close()

    @staticmethod
    def unfreeze_function(emulator_id: int, function_name: str,
                          db_path: str = None):
        """Разморозить функцию принудительно"""
        if db_path is None:
            db_path = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            conn.execute("""
                DELETE FROM function_freeze 
                WHERE emulator_id = ? AND function_name = ?
            """, (emulator_id, function_name))
            conn.commit()
            logger.info(f"✅ [{function_name}] Эмулятор {emulator_id} разморожен")
        finally:
            conn.close()

    # ===== УДОБНЫЕ ОБЁРТКИ ДЛЯ ЭВОЛЮЦИИ =====

    def freeze_evolution(self, emulator_id: int, hours: int = 4,
                         reason: str = "Нехватка ресурсов"):
        """Заморозить эволюцию на эмуляторе"""
        self.freeze_function(emulator_id, 'evolution', hours, reason)

    def is_evolution_frozen(self, emulator_id: int) -> bool:
        """Проверить заморожена ли эволюция"""
        return self.is_function_frozen(emulator_id, 'evolution')

    def get_evolution_freeze_until(self, emulator_id: int) -> Optional[datetime]:
        """Время разморозки эволюции"""
        return self.get_function_freeze_until(emulator_id, 'evolution')

    # ===== МЕТОДЫ ДЛЯ ПЛАНИРОВЩИКА =====

    def get_nearest_research_finish_time(self, emulator_id: int) -> Optional[datetime]:
        """
        Время завершения текущего исследования

        Используется планировщиком для определения когда нужен эмулятор.

        Returns:
            datetime или None
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT finish_time FROM evolution_slot 
                WHERE emulator_id = ? AND is_busy = 1 AND finish_time IS NOT NULL
            """, (emulator_id,))

            row = cursor.fetchone()
            if not row or not row['finish_time']:
                return None

            finish_time = row['finish_time']
            if isinstance(finish_time, str):
                finish_time = datetime.fromisoformat(finish_time)

            return finish_time if finish_time > datetime.now() else None

    # ===== КОНФИГУРАЦИЯ СВАЙПОВ =====

    def get_swipe_config(self, section_name: str) -> Dict:
        """
        Получить конфигурацию свайпов для раздела

        Returns:
            dict с ключами 'swipe_1', 'swipe_2' — координаты [x1, y1, x2, y2]
            или пустой dict если свайпы не нужны
        """
        config = self._load_config()
        swipe_cfg = config.get('swipe_config', {})
        return swipe_cfg.get(section_name, {})