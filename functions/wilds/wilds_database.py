"""
База данных для охоты на диких существ

Хранит:
- Энергию отрядов (wilds_squads)
- Состояние складов ресурсов (wilds_resources)

Используется для:
- Расчёта времени восстановления энергии
- Определения когда запускать эмулятор (планировщик)
- Приоритизации ресурсов для охоты

Версия: 1.0
Дата создания: 2025-03-11
"""

import os
import math
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from utils.logger import logger

# Базовая директория проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Время восстановления 1 единицы энергии (секунды)
ENERGY_REGEN_SECONDS = 480

# Порог энергии для запуска охоты (не ждём до 100)
ENERGY_THRESHOLD = 90

# Стоимость 1 атаки в единицах энергии
ENERGY_PER_ATTACK = 10

# Добыча ресурсов по уровню дикого (в тысячах K)
WILD_LOOT = {
    15: 330.4, 14: 308.0, 13: 287.0, 12: 252.8,
    11: 224.0, 10: 199.6, 9: 178.4, 8: 156.0,
    7: 138.6, 6: 112.0, 5: 94.1, 4: 79.8,
    3: 22.4, 2: 15.4, 1: 11.2
}

# Маппинг ресурсов: ключ БД → координаты панели ресурсов
RESOURCE_COORDS = {
    'apples': (43, 19),
    'leaves': (199, 19),
    'soil': (348, 19),
    'sand': (426, 19),
    # honey — не парсим, нет ограничений
}

# Маппинг ключей ресурсов → русские названия (для логов)
RESOURCE_NAMES_RU = {
    'apples': 'Яблоки',
    'leaves': 'Листья',
    'soil': 'Грунт',
    'sand': 'Песок',
    'honey': 'Мёд',
}

# Маппинг ключей отрядов → русские названия
SQUAD_NAMES_RU = {
    'special': 'Особый Отряд',
    'squad_1': 'Отряд I',
    'squad_2': 'Отряд II',
    'squad_3': 'Отряд III',
}


class WildsDatabase:
    """
    БД для охоты на диких существ

    Таблицы:
    - wilds_squads: энергия отрядов, время последнего парсинга
    - wilds_resources: состояние складов ресурсов
    """

    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    def __init__(self):
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        self.db_lock = threading.RLock()
        self.conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        self._create_tables()
        logger.info("✅ WildsDatabase инициализирована")

    # ==================== СОЗДАНИЕ ТАБЛИЦ ====================

    def _create_tables(self):
        """Создать таблицы если их нет"""
        with self.db_lock:
            cursor = self.conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wilds_squads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    squad_key TEXT NOT NULL,
                    last_energy INTEGER DEFAULT 100,
                    energy_updated_at TIMESTAMP,
                    UNIQUE(emulator_id, squad_key)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wilds_resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    resource_type TEXT NOT NULL,
                    stored_amount REAL,
                    storage_capacity REAL,
                    last_parsed_at TIMESTAMP,
                    UNIQUE(emulator_id, resource_type)
                )
            """)

            self.conn.commit()

    # ==================== ЭНЕРГИЯ ОТРЯДОВ ====================

    def update_squad_energy(self, emulator_id: int, squad_key: str,
                            energy: int, timestamp: Optional[datetime] = None):
        """
        Обновить энергию отряда

        Args:
            emulator_id: ID эмулятора
            squad_key: 'special', 'squad_1', 'squad_2', 'squad_3'
            energy: текущая энергия (0-100)
            timestamp: время парсинга (по умолчанию now)
        """
        ts = timestamp or datetime.now()
        with self.db_lock:
            self.conn.execute("""
                INSERT INTO wilds_squads (emulator_id, squad_key, last_energy, energy_updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(emulator_id, squad_key)
                DO UPDATE SET last_energy = excluded.last_energy,
                              energy_updated_at = excluded.energy_updated_at
            """, (emulator_id, squad_key, energy, ts.isoformat()))
            self.conn.commit()

        squad_name = SQUAD_NAMES_RU.get(squad_key, squad_key)
        logger.debug(
            f"[Emulator {emulator_id}] 🔋 {squad_name}: "
            f"энергия={energy}/100"
        )

    def get_squad_energy(self, emulator_id: int, squad_key: str) -> Optional[Dict]:
        """
        Получить данные об энергии отряда

        Returns:
            dict: {last_energy, energy_updated_at} или None
        """
        with self.db_lock:
            cursor = self.conn.execute("""
                SELECT last_energy, energy_updated_at
                FROM wilds_squads
                WHERE emulator_id = ? AND squad_key = ?
            """, (emulator_id, squad_key))
            row = cursor.fetchone()

        if not row:
            return None

        updated_at = None
        if row['energy_updated_at']:
            try:
                updated_at = datetime.fromisoformat(row['energy_updated_at'])
            except (ValueError, TypeError):
                updated_at = None

        return {
            'last_energy': row['last_energy'],
            'energy_updated_at': updated_at,
        }

    def get_current_energy(self, emulator_id: int, squad_key: str) -> int:
        """
        Рассчитать текущую энергию с учётом восстановления

        Формула: min(100, last_energy + elapsed_seconds // 480)

        Returns:
            int: текущая расчётная энергия (0-100)
        """
        data = self.get_squad_energy(emulator_id, squad_key)
        if not data or not data['energy_updated_at']:
            return 0  # Нет данных — считаем 0

        elapsed = (datetime.now() - data['energy_updated_at']).total_seconds()
        recovered = int(elapsed / ENERGY_REGEN_SECONDS)
        return min(100, data['last_energy'] + recovered)

    def get_available_attacks(self, emulator_id: int,
                              enabled_squads: List[str]) -> int:
        """
        Сколько атак доступно суммарно по всем включённым отрядам

        Args:
            enabled_squads: ['special', 'squad_1', ...]

        Returns:
            int: суммарное кол-во доступных атак
        """
        total = 0
        for squad_key in enabled_squads:
            energy = self.get_current_energy(emulator_id, squad_key)
            total += math.floor(energy / ENERGY_PER_ATTACK)
        return total

    def is_energy_sufficient(self, emulator_id: int,
                              enabled_squads: Optional[List[str]] = None) -> bool:
        """
        Достаточно ли энергии для запуска охоты?

        Проверяет что хотя бы один отряд имеет энергию >= ENERGY_THRESHOLD

        Args:
            enabled_squads: список включённых отрядов.
                           Если None — проверяет все отряды в БД для этого эмулятора

        Returns:
            bool: True если можно начинать охоту
        """
        if enabled_squads is None:
            # Достать все отряды из БД
            with self.db_lock:
                cursor = self.conn.execute("""
                    SELECT squad_key FROM wilds_squads
                    WHERE emulator_id = ?
                """, (emulator_id,))
                enabled_squads = [row['squad_key'] for row in cursor.fetchall()]

        if not enabled_squads:
            return True  # Нет данных — первый запуск, пробуем

        for squad_key in enabled_squads:
            energy = self.get_current_energy(emulator_id, squad_key)
            if energy >= ENERGY_THRESHOLD:
                return True

        return False

    def get_estimated_full_energy_time(self, emulator_id: int,
                                        enabled_squads: Optional[List[str]] = None) -> Optional[datetime]:
        """
        Когда ВСЕ задействованные отряды будут >= ENERGY_THRESHOLD?

        Returns:
            datetime: время когда энергия восстановится
            None: нет данных
        """
        if enabled_squads is None:
            with self.db_lock:
                cursor = self.conn.execute("""
                    SELECT squad_key FROM wilds_squads
                    WHERE emulator_id = ?
                """, (emulator_id,))
                enabled_squads = [row['squad_key'] for row in cursor.fetchall()]

        if not enabled_squads:
            return None  # Нет данных

        max_wait = timedelta(0)

        for squad_key in enabled_squads:
            current = self.get_current_energy(emulator_id, squad_key)
            needed = max(0, ENERGY_THRESHOLD - current)
            wait = timedelta(seconds=needed * ENERGY_REGEN_SECONDS)
            max_wait = max(max_wait, wait)

        if max_wait == timedelta(0):
            return datetime.now()  # Уже готовы

        return datetime.now() + max_wait

    # ==================== РЕСУРСЫ СКЛАДОВ ====================

    def update_resource(self, emulator_id: int, resource_type: str,
                        stored: float, capacity: float,
                        timestamp: Optional[datetime] = None):
        """
        Обновить данные о ресурсе на складе

        Args:
            resource_type: 'apples', 'leaves', 'soil', 'sand', 'honey'
            stored: текущее кол-во (в тысячах K)
            capacity: вместимость склада (в тысячах K)
        """
        ts = timestamp or datetime.now()
        with self.db_lock:
            self.conn.execute("""
                INSERT INTO wilds_resources 
                    (emulator_id, resource_type, stored_amount, storage_capacity, last_parsed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(emulator_id, resource_type)
                DO UPDATE SET stored_amount = excluded.stored_amount,
                              storage_capacity = excluded.storage_capacity,
                              last_parsed_at = excluded.last_parsed_at
            """, (emulator_id, resource_type, stored, capacity, ts.isoformat()))
            self.conn.commit()

        name_ru = RESOURCE_NAMES_RU.get(resource_type, resource_type)
        fill_pct = (stored / capacity * 100) if capacity > 0 else 0
        logger.debug(
            f"[Emulator {emulator_id}] 📦 {name_ru}: "
            f"{stored:.1f}K / {capacity:.1f}K ({fill_pct:.0f}%)"
        )

    def get_resource(self, emulator_id: int, resource_type: str) -> Optional[Dict]:
        """
        Получить данные о ресурсе

        Returns:
            dict: {stored_amount, storage_capacity, fill_percent, last_parsed_at}
        """
        with self.db_lock:
            cursor = self.conn.execute("""
                SELECT stored_amount, storage_capacity, last_parsed_at
                FROM wilds_resources
                WHERE emulator_id = ? AND resource_type = ?
            """, (emulator_id, resource_type))
            row = cursor.fetchone()

        if not row or row['storage_capacity'] is None:
            return None

        stored = row['stored_amount'] or 0
        capacity = row['storage_capacity'] or 1
        fill_pct = (stored / capacity * 100) if capacity > 0 else 0

        parsed_at = None
        if row['last_parsed_at']:
            try:
                parsed_at = datetime.fromisoformat(row['last_parsed_at'])
            except (ValueError, TypeError):
                parsed_at = None

        return {
            'stored_amount': stored,
            'storage_capacity': capacity,
            'fill_percent': fill_pct,
            'last_parsed_at': parsed_at,
        }

    def get_all_resources(self, emulator_id: int) -> Dict[str, Dict]:
        """
        Получить все ресурсы для эмулятора

        Returns:
            dict: {resource_type: {stored_amount, storage_capacity, fill_percent}}
        """
        result = {}
        for res_type in ['apples', 'leaves', 'soil', 'sand', 'honey']:
            data = self.get_resource(emulator_id, res_type)
            if data:
                result[res_type] = data
        return result

    # ==================== УТИЛИТЫ ====================

    def has_data(self, emulator_id: int) -> bool:
        """Есть ли данные об энергии для эмулятора (был ли хотя бы один запуск)"""
        with self.db_lock:
            cursor = self.conn.execute("""
                SELECT COUNT(*) as cnt FROM wilds_squads
                WHERE emulator_id = ?
            """, (emulator_id,))
            return cursor.fetchone()['cnt'] > 0

    def clear_emulator_data(self, emulator_id: int):
        """Удалить все данные по эмулятору (для сброса)"""
        with self.db_lock:
            self.conn.execute(
                "DELETE FROM wilds_squads WHERE emulator_id = ?",
                (emulator_id,)
            )
            self.conn.execute(
                "DELETE FROM wilds_resources WHERE emulator_id = ?",
                (emulator_id,)
            )
            self.conn.commit()
        logger.info(f"[Emulator {emulator_id}] 🗑️ Данные wilds очищены")

    # ==================== СТАТИЧЕСКИЕ МЕТОДЫ ДЛЯ ПЛАНИРОВЩИКА ====================

    @staticmethod
    def get_next_hunt_time(emulator_id: int) -> Optional[datetime]:
        """
        Когда нужен эмулятор для охоты на диких?

        Статический метод для планировщика (не требует экземпляра).

        Логика:
        1. Функция заморожена → время разморозки
        2. Нет данных в БД → datetime.min (первый запуск, нужен сразу)
        3. Энергия >= ENERGY_THRESHOLD → datetime.now() (готов)
        4. Энергия < ENERGY_THRESHOLD → время восстановления

        Returns:
            datetime: когда нужен эмулятор
            None: wilds не нужны (все ресурсы выключены и т.д.)
        """
        from utils.function_freeze_manager import function_freeze_manager

        # Заморожена?
        if function_freeze_manager.is_frozen(emulator_id, 'wilds'):
            unfreeze_at = function_freeze_manager.get_unfreeze_time(
                emulator_id, 'wilds'
            )
            if unfreeze_at:
                return unfreeze_at
            return None

        # Подключаемся к БД
        db_path = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

        try:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row

            # Проверяем есть ли таблица
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='wilds_squads'
            """)
            if not cursor.fetchone():
                conn.close()
                return datetime.min  # Таблицы нет — первый запуск

            # Проверяем есть ли данные
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM wilds_squads
                WHERE emulator_id = ?
            """, (emulator_id,))
            if cursor.fetchone()['cnt'] == 0:
                conn.close()
                return datetime.min  # Нет данных — первый запуск

            # Считаем время восстановления для каждого отряда
            cursor.execute("""
                SELECT squad_key, last_energy, energy_updated_at
                FROM wilds_squads
                WHERE emulator_id = ?
            """, (emulator_id,))

            max_wait = timedelta(0)
            now = datetime.now()

            for row in cursor.fetchall():
                last_energy = row['last_energy']
                updated_at_str = row['energy_updated_at']

                if not updated_at_str:
                    conn.close()
                    return datetime.min

                try:
                    updated_at = datetime.fromisoformat(updated_at_str)
                except (ValueError, TypeError):
                    conn.close()
                    return datetime.min

                # Сколько восстановилось с момента парсинга
                elapsed = (now - updated_at).total_seconds()
                recovered = int(elapsed / ENERGY_REGEN_SECONDS)
                current = min(100, last_energy + recovered)

                # Сколько ещё нужно до ENERGY_THRESHOLD
                needed = max(0, ENERGY_THRESHOLD - current)
                wait = timedelta(seconds=needed * ENERGY_REGEN_SECONDS)
                max_wait = max(max_wait, wait)

            conn.close()

            if max_wait == timedelta(0):
                return now  # Уже готовы
            return now + max_wait

        except Exception as e:
            logger.error(f"[Emulator {emulator_id}] ❌ WildsDatabase.get_next_hunt_time: {e}")
            return None

    def close(self):
        """Закрыть соединение с БД"""
        try:
            self.conn.close()
        except Exception:
            pass