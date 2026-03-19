"""
База данных для модуля тренировки войск

Таблицы:
- training_slots: слоты тренировки (1 на здание, аналог builders)
- troop_counts: количество юнитов по типам (для будущих прайм-таймов)

Также обеспечивает точечную инициализацию зданий Логово Плотоядных
и Логово Всеядных в таблице buildings (если их нет).

Версия: 1.0
Дата создания: 2025-03-19
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

from utils.logger import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ==================== КОНСТАНТЫ ====================

# Здания тренировки
TRAINING_BUILDINGS = {
    'carnivore': {
        'building_name': 'Логово Плотоядных',
        'building_type': 'unique',
        'target_level': 25,       # Макс уровень в игре
        'action': 'upgrade',
    },
    'omnivore': {
        'building_name': 'Логово Всеядных',
        'building_type': 'unique',
        'target_level': 25,
        'action': 'upgrade',
    },
}

# Маппинг тиров → названия юнитов
TROOP_INFO = {
    'carnivore': {
        4: {'name': 'Шакал', 'name_region': (222, 92, 313, 124)},
        5: {'name': 'Гривистый Волк', 'name_region': (174, 97, 361, 124)},
    },
    'omnivore': {
        1: {'name': 'Макака', 'name_region': (174, 97, 361, 124)},
    },
}

# Область парсинга количества юнитов: "Имеется: 14,720"
UNIT_COUNT_REGION = (186, 126, 353, 151)

# Область парсинга таймера обучения
TRAINING_TIMER_REGION = (210, 803, 330, 837)

# Уровень Логова Плотоядных для разблокировки Т5
TIER5_UNLOCK_LEVEL = 13

# Русские названия для логов
BUILDING_TYPE_NAMES_RU = {
    'carnivore': 'Плотоядные',
    'omnivore': 'Всеядные',
}


class TrainingDatabase:
    """
    БД модуля тренировки

    Управляет:
    - training_slots: 2 слота (carnivore / omnivore), таймеры тренировки
    - troop_counts: количество юнитов по типам
    - Точечная инициализация зданий в buildings (если отсутствуют)
    """

    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    def __init__(self):
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        self.conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.db_lock = threading.RLock()

        self._ensure_tables()

        logger.info("✅ TrainingDatabase инициализирована")

    def _ensure_tables(self):
        """Создать таблицы если не существуют"""
        with self.db_lock:
            cursor = self.conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS training_slots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    building_type TEXT NOT NULL,
                    is_training BOOLEAN NOT NULL DEFAULT 0,
                    tier INTEGER,
                    finish_time TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(emulator_id, building_type)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS troop_counts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    troop_name TEXT NOT NULL,
                    troop_tier INTEGER NOT NULL,
                    troop_type TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    last_parsed_at TIMESTAMP,
                    UNIQUE(emulator_id, troop_name)
                )
            """)

            self.conn.commit()

    # ==================== ИНИЦИАЛИЗАЦИЯ ====================

    def ensure_initialized(self, emulator_id: int) -> bool:
        """
        Убедиться что слоты тренировки созданы для эмулятора

        Создаёт 2 слота (carnivore, omnivore) если их нет.
        Идемпотентная операция — безопасно вызывать повторно.

        Returns:
            True — слоты готовы
        """
        with self.db_lock:
            cursor = self.conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) FROM training_slots WHERE emulator_id = ?",
                (emulator_id,)
            )
            count = cursor.fetchone()[0]

            if count >= 2:
                return True

            # Создаём недостающие слоты
            for building_type in ('carnivore', 'omnivore'):
                cursor.execute("""
                    INSERT OR IGNORE INTO training_slots
                        (emulator_id, building_type, is_training)
                    VALUES (?, ?, 0)
                """, (emulator_id, building_type))

            self.conn.commit()
            logger.info(
                f"[Emulator {emulator_id}] ✅ Слоты тренировки инициализированы"
            )

        return True

    def ensure_buildings_in_db(self, emulator_id: int) -> Dict[str, bool]:
        """
        Убедиться что Логово Плотоядных и Логово Всеядных есть в таблице buildings

        Проверяет каждое здание. Если отсутствует — создаёт запись с level=0.
        НЕ сканирует уровень — это делает TrainingFunction через NavigationPanel.

        Returns:
            dict: {'carnivore': True/False, 'omnivore': True/False}
                  True = здание уже было в БД (level известен)
                  False = здание создано с level=0 (нужно сканировать)
        """
        result = {}

        with self.db_lock:
            cursor = self.conn.cursor()

            for btype, info in TRAINING_BUILDINGS.items():
                building_name = info['building_name']

                cursor.execute("""
                    SELECT current_level FROM buildings
                    WHERE emulator_id = ? AND building_name = ?
                    LIMIT 1
                """, (emulator_id, building_name))

                row = cursor.fetchone()

                if row is not None:
                    # Здание есть в БД
                    level = row['current_level']
                    result[btype] = (level > 0)

                    if level > 0:
                        logger.debug(
                            f"[Emulator {emulator_id}] ✅ {building_name} "
                            f"уже в БД: Lv.{level}"
                        )
                    else:
                        logger.info(
                            f"[Emulator {emulator_id}] ⚠️ {building_name} "
                            f"в БД, но level=0 (нужно сканировать)"
                        )
                        result[btype] = False
                else:
                    # Здания нет в БД — создаём
                    cursor.execute("""
                        INSERT INTO buildings
                            (emulator_id, building_name, building_type,
                             building_index, current_level, target_level,
                             status, action)
                        VALUES (?, ?, ?, NULL, 0, ?, 'idle', ?)
                    """, (
                        emulator_id,
                        building_name,
                        info['building_type'],
                        info['target_level'],
                        info['action'],
                    ))

                    logger.info(
                        f"[Emulator {emulator_id}] 🆕 {building_name} "
                        f"добавлено в БД (level=0, нужно сканировать)"
                    )
                    result[btype] = False

            self.conn.commit()

        return result

    # ==================== УРОВЕНЬ ЗДАНИЯ ====================

    def get_building_level(self, emulator_id: int,
                           building_type: str) -> Optional[int]:
        """
        Получить текущий уровень здания тренировки из таблицы buildings

        Args:
            building_type: 'carnivore' или 'omnivore'

        Returns:
            int: уровень здания или None
        """
        info = TRAINING_BUILDINGS.get(building_type)
        if not info:
            return None

        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT current_level FROM buildings
                WHERE emulator_id = ? AND building_name = ?
                LIMIT 1
            """, (emulator_id, info['building_name']))

            row = cursor.fetchone()
            return row['current_level'] if row else None

    def get_carnivore_tier(self, emulator_id: int) -> int:
        """
        Определить тир плотоядных на основе уровня Логова

        Returns:
            5 если Логово Плотоядных >= 13, иначе 4
        """
        level = self.get_building_level(emulator_id, 'carnivore')

        if level is None:
            logger.warning(
                f"[Emulator {emulator_id}] ⚠️ Уровень Логова Плотоядных "
                f"неизвестен, используем Т4 по умолчанию"
            )
            return 4

        tier = 5 if level >= TIER5_UNLOCK_LEVEL else 4
        logger.debug(
            f"[Emulator {emulator_id}] Логово Плотоядных Lv.{level} "
            f"→ Т{tier}"
        )
        return tier

    # ==================== СЛОТЫ ТРЕНИРОВКИ ====================

    def get_slot(self, emulator_id: int,
                 building_type: str) -> Optional[Dict]:
        """
        Получить информацию о слоте тренировки

        Returns:
            dict: {building_type, is_training, tier, finish_time} или None
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT building_type, is_training, tier, finish_time
                FROM training_slots
                WHERE emulator_id = ? AND building_type = ?
            """, (emulator_id, building_type))

            row = cursor.fetchone()
            if row is None:
                return None

            return {
                'building_type': row['building_type'],
                'is_training': bool(row['is_training']),
                'tier': row['tier'],
                'finish_time': (
                    datetime.fromisoformat(row['finish_time'])
                    if row['finish_time'] else None
                ),
            }

    def is_slot_free(self, emulator_id: int,
                     building_type: str) -> bool:
        """Свободен ли слот тренировки?"""
        slot = self.get_slot(emulator_id, building_type)
        if slot is None:
            return True
        return not slot['is_training']

    def start_training(self, emulator_id: int, building_type: str,
                       tier: int, timer_seconds: int):
        """
        Записать начало тренировки

        Args:
            building_type: 'carnivore' / 'omnivore'
            tier: тир юнита (1, 4, 5)
            timer_seconds: время тренировки в секундах
        """
        finish_time = datetime.now() + timedelta(seconds=timer_seconds)
        type_name = BUILDING_TYPE_NAMES_RU.get(building_type, building_type)

        with self.db_lock:
            self.conn.execute("""
                UPDATE training_slots
                SET is_training = 1,
                    tier = ?,
                    finish_time = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_type = ?
            """, (tier, finish_time.isoformat(), emulator_id, building_type))
            self.conn.commit()

        logger.info(
            f"[Emulator {emulator_id}] 🎓 {type_name} Т{tier}: "
            f"тренировка до {finish_time.strftime('%H:%M:%S')}"
        )

    def clear_finished_slots(self, emulator_id: int) -> int:
        """
        Освободить слоты с истёкшим таймером

        Returns:
            int: количество освобождённых слотов
        """
        now = datetime.now().isoformat()

        with self.db_lock:
            cursor = self.conn.cursor()

            # Найти истёкшие
            cursor.execute("""
                SELECT building_type, tier FROM training_slots
                WHERE emulator_id = ? AND is_training = 1
                  AND finish_time <= ?
            """, (emulator_id, now))

            finished = cursor.fetchall()

            if not finished:
                return 0

            # Освободить
            cursor.execute("""
                UPDATE training_slots
                SET is_training = 0,
                    tier = NULL,
                    finish_time = NULL,
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND is_training = 1
                  AND finish_time <= ?
            """, (emulator_id, now))

            self.conn.commit()

        for row in finished:
            type_name = BUILDING_TYPE_NAMES_RU.get(
                row['building_type'], row['building_type']
            )
            logger.info(
                f"[Emulator {emulator_id}] ✅ {type_name} Т{row['tier']}: "
                f"тренировка завершена, слот свободен"
            )

        return len(finished)

    def get_free_slots(self, emulator_id: int) -> List[str]:
        """
        Получить список свободных слотов

        Returns:
            ['carnivore', 'omnivore'] или подмножество
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT building_type FROM training_slots
                WHERE emulator_id = ? AND is_training = 0
            """, (emulator_id,))

            return [row['building_type'] for row in cursor.fetchall()]

    def get_nearest_finish_time(self,
                                emulator_id: int) -> Optional[datetime]:
        """
        Ближайшее время завершения тренировки

        Используется планировщиком для определения когда нужен эмулятор.

        Returns:
            datetime или None (нет активных тренировок)
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT MIN(finish_time) as nearest
                FROM training_slots
                WHERE emulator_id = ? AND is_training = 1
                  AND finish_time IS NOT NULL
            """, (emulator_id,))

            row = cursor.fetchone()
            if row and row['nearest']:
                return datetime.fromisoformat(row['nearest'])

        return None

    def has_active_training(self, emulator_id: int) -> bool:
        """Есть ли активная тренировка?"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT 1 FROM training_slots
                WHERE emulator_id = ? AND is_training = 1
                LIMIT 1
            """, (emulator_id,))
            return cursor.fetchone() is not None

    # ==================== КОЛИЧЕСТВО ЮНИТОВ ====================

    def update_troop_count(self, emulator_id: int, troop_name: str,
                           tier: int, troop_type: str, count: int):
        """
        Обновить количество юнитов

        Args:
            troop_name: 'Шакал', 'Гривистый Волк', 'Макака'
            tier: 1, 4, 5
            troop_type: 'carnivore' / 'omnivore'
            count: количество юнитов
        """
        with self.db_lock:
            self.conn.execute("""
                INSERT INTO troop_counts
                    (emulator_id, troop_name, troop_tier, troop_type,
                     count, last_parsed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(emulator_id, troop_name)
                DO UPDATE SET
                    count = excluded.count,
                    last_parsed_at = excluded.last_parsed_at
            """, (
                emulator_id, troop_name, tier, troop_type,
                count, datetime.now().isoformat()
            ))
            self.conn.commit()

        logger.debug(
            f"[Emulator {emulator_id}] 📊 {troop_name} (Т{tier}): "
            f"{count:,} юнитов"
        )

    def get_troop_count(self, emulator_id: int,
                        troop_name: str) -> Optional[int]:
        """Получить количество юнитов по имени"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT count FROM troop_counts
                WHERE emulator_id = ? AND troop_name = ?
            """, (emulator_id, troop_name))

            row = cursor.fetchone()
            return row['count'] if row else None

    def get_all_troop_counts(self,
                             emulator_id: int) -> List[Dict]:
        """Получить все юниты для эмулятора"""
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT troop_name, troop_tier, troop_type, count,
                       last_parsed_at
                FROM troop_counts
                WHERE emulator_id = ?
                ORDER BY troop_type, troop_tier
            """, (emulator_id,))

            return [dict(row) for row in cursor.fetchall()]