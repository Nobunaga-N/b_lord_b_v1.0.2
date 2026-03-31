"""
Хранилище инвентаря ускорений (speedup_inventory)

Таблица в общей bot.db:
  emulator_id  — ID эмулятора
  speedup_type — universal/building/evolution/training
  denomination — 1m/5m/10m/15m/1h/2h/3h/8h/1d/5d
  quantity     — кол-во предметов
  last_updated — время последнего обновления

Методы:
  save_inventory()    — сохранить результат парсинга рюкзака
  has_data()          — есть ли данные для эмулятора
  get_inventory()     — получить инвентарь
  get_total_seconds() — суммарные секунды ускорений
  use_speedup()       — декремент quantity (после траты ускорения)
  get_quantity()      — получить quantity конкретного номинала

Версия: 1.1 — добавлены use_speedup(), get_quantity() для prime_times
"""

import os
import sqlite3
import threading
from datetime import datetime
from typing import Dict, Optional

from utils.logger import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Конвертация номиналов в секунды
DENOM_SECONDS = {
    '1m': 60, '5m': 300, '10m': 600, '15m': 900,
    '1h': 3600, '2h': 7200, '3h': 10800, '8h': 28800,
    '1d': 86400, '5d': 432000,
}

DENOM_ORDER = ['1m', '5m', '10m', '15m', '1h', '2h', '3h', '8h', '1d', '5d']


class BackpackStorage:
    """
    Хранилище инвентаря ускорений в SQLite

    Thread-safe через RLock.
    Использует общую bot.db.
    """

    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    def __init__(self):
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

        self._create_table()
        logger.debug("✅ BackpackStorage инициализирован")

    def _create_table(self):
        """Создать таблицу если не существует"""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS speedup_inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    speedup_type TEXT NOT NULL,
                    denomination TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(emulator_id, speedup_type, denomination)
                )
            """)
            self._conn.commit()

    # ==================== ЗАПИСЬ ====================

    def save_inventory(
        self,
        emulator_id: int,
        parsed: Dict[str, Dict[str, int]]
    ):
        """
        Сохранить результат парсинга рюкзака в БД.

        Полная перезапись: DELETE + INSERT.
        Гарантирует что израсходованные предметы не останутся в БД.

        Args:
            emulator_id: ID эмулятора
            parsed: {speedup_type: {denomination: quantity}}
        """
        if emulator_id is None:
            logger.error("❌ BackpackStorage.save_inventory: emulator_id is None")
            return

        now = datetime.now().isoformat()
        total_items = 0

        with self._lock:
            cursor = self._conn.cursor()

            # Удаляем старые записи
            cursor.execute(
                "DELETE FROM speedup_inventory WHERE emulator_id = ?",
                (emulator_id,)
            )

            # Вставляем новые
            for stype, denoms in parsed.items():
                for denom, qty in denoms.items():
                    if qty <= 0:
                        continue
                    cursor.execute("""
                        INSERT INTO speedup_inventory 
                            (emulator_id, speedup_type, denomination, quantity, last_updated)
                        VALUES (?, ?, ?, ?, ?)
                    """, (emulator_id, stype, denom, qty, now))
                    total_items += 1

            self._conn.commit()

        total_sec = self._calc_total_seconds(parsed)
        hours = total_sec / 3600
        logger.info(
            f"[Emulator {emulator_id}] 💾 Ускорения сохранены: "
            f"{total_items} позиций, {hours:.1f}ч суммарно"
        )

    # ==================== ЧТЕНИЕ ====================

    def has_data(self, emulator_id: int) -> bool:
        """Есть ли данные об ускорениях для эмулятора"""
        if emulator_id is None:
            return False

        with self._lock:
            cursor = self._conn.execute(
                "SELECT 1 FROM speedup_inventory WHERE emulator_id = ? LIMIT 1",
                (emulator_id,)
            )
            return cursor.fetchone() is not None

    def get_inventory(
        self,
        emulator_id: int,
        speedup_type: Optional[str] = None
    ) -> Dict[str, Dict[str, int]]:
        """
        Получить инвентарь ускорений из БД.

        Args:
            emulator_id: ID эмулятора
            speedup_type: фильтр по типу (None = все)

        Returns:
            {speedup_type: {denomination: quantity}}
        """
        if emulator_id is None:
            return {}

        with self._lock:
            if speedup_type:
                cursor = self._conn.execute("""
                    SELECT speedup_type, denomination, quantity
                    FROM speedup_inventory
                    WHERE emulator_id = ? AND speedup_type = ?
                    ORDER BY speedup_type, denomination
                """, (emulator_id, speedup_type))
            else:
                cursor = self._conn.execute("""
                    SELECT speedup_type, denomination, quantity
                    FROM speedup_inventory
                    WHERE emulator_id = ?
                    ORDER BY speedup_type, denomination
                """, (emulator_id,))

            rows = cursor.fetchall()

        result: Dict[str, Dict[str, int]] = {}
        for row in rows:
            stype = row['speedup_type']
            denom = row['denomination']
            qty = row['quantity']

            if stype not in result:
                result[stype] = {}
            result[stype][denom] = qty

        return result

    def get_total_seconds(
        self,
        emulator_id: int,
        speedup_type: Optional[str] = None
    ) -> int:
        """
        Суммарные секунды ускорений для эмулятора.

        Args:
            emulator_id: ID эмулятора
            speedup_type: фильтр по типу (None = все)

        Returns:
            int: суммарные секунды
        """
        inventory = self.get_inventory(emulator_id, speedup_type)
        return self._calc_total_seconds(inventory)

    def get_quantity(
        self,
        emulator_id: int,
        speedup_type: str,
        denomination: str
    ) -> int:
        """
        Получить текущий quantity конкретного номинала.

        Args:
            emulator_id: ID эмулятора
            speedup_type: тип ускорения ('building', 'universal', ...)
            denomination: номинал ('1m', '5m', '1h', ...)

        Returns:
            int: quantity (0 если записи нет)
        """
        if emulator_id is None:
            return 0

        with self._lock:
            cursor = self._conn.execute("""
                SELECT quantity FROM speedup_inventory
                WHERE emulator_id = ? AND speedup_type = ? AND denomination = ?
            """, (emulator_id, speedup_type, denomination))

            row = cursor.fetchone()

        return row['quantity'] if row else 0

    # ==================== РАСХОД УСКОРЕНИЙ ====================

    def use_speedup(
        self,
        emulator_id: int,
        speedup_type: str,
        denomination: str,
        count: int = 1
    ) -> int:
        """
        Уменьшить quantity после использования ускорения.

        Декремент на count. Если quantity <= 0 — удаляет запись.
        Вызывается из speedup_applier после каждого клика "Использовать".

        Args:
            emulator_id: ID эмулятора
            speedup_type: тип ускорения
            denomination: номинал
            count: сколько штук потрачено (обычно 1)

        Returns:
            int: новый quantity (0 если запись удалена или не найдена)
        """
        if emulator_id is None:
            logger.error("❌ BackpackStorage.use_speedup: emulator_id is None")
            return 0

        now = datetime.now().isoformat()

        with self._lock:
            # Читаем текущее значение
            cursor = self._conn.execute("""
                SELECT quantity FROM speedup_inventory
                WHERE emulator_id = ? AND speedup_type = ? AND denomination = ?
            """, (emulator_id, speedup_type, denomination))

            row = cursor.fetchone()

            if row is None:
                logger.warning(
                    f"[Emulator {emulator_id}] ⚠️ use_speedup: "
                    f"запись {speedup_type}/{denomination} не найдена"
                )
                return 0

            old_qty = row['quantity']
            new_qty = max(0, old_qty - count)

            if new_qty <= 0:
                # Удаляем запись — номинал закончился
                self._conn.execute("""
                    DELETE FROM speedup_inventory
                    WHERE emulator_id = ? AND speedup_type = ? AND denomination = ?
                """, (emulator_id, speedup_type, denomination))

                logger.debug(
                    f"[Emulator {emulator_id}] 🗑️ {speedup_type}/{denomination}: "
                    f"{old_qty} → 0 (удалена)"
                )
            else:
                # Декремент
                self._conn.execute("""
                    UPDATE speedup_inventory
                    SET quantity = ?, last_updated = ?
                    WHERE emulator_id = ? AND speedup_type = ? AND denomination = ?
                """, (new_qty, now, emulator_id, speedup_type, denomination))

                logger.debug(
                    f"[Emulator {emulator_id}] ⬇️ {speedup_type}/{denomination}: "
                    f"{old_qty} → {new_qty}"
                )

            self._conn.commit()

        return new_qty

    # ==================== УТИЛИТЫ ====================

    @staticmethod
    def _calc_total_seconds(parsed: Dict[str, Dict[str, int]]) -> int:
        """Подсчитать суммарные секунды из parsed dict"""
        total = 0
        for denoms in parsed.values():
            for denom, qty in denoms.items():
                total += DENOM_SECONDS.get(denom, 0) * qty
        return total

    def close(self):
        """Закрыть соединение с БД"""
        try:
            self._conn.close()
        except Exception:
            pass