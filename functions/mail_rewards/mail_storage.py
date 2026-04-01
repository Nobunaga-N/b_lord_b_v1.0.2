"""
Хранилище сбора наград с почты (mail_rewards_log)

Таблица в общей bot.db:
  emulator_id      — ID эмулятора (PRIMARY KEY)
  last_collected_at — время последнего сбора наград
  last_updated      — время обновления записи

Назначение:
  - Отслеживание когда последний раз собирали почту
  - 48-часовой самотриггер: если > 48ч без сбора → get_next_event_time()
    возвращает datetime.now() → планировщик запускает эмулятор
  - Предотвращение повторного сбора в рамках одной сессии (через session_state)

Thread-safe через RLock.

Версия: 1.0
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional

from utils.logger import logger

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Порог самотриггера (часы)
SELF_TRIGGER_HOURS = 48


class MailStorage:
    """
    CRUD для таблицы mail_rewards_log в bot.db

    Хранит время последнего сбора наград с почты
    для каждого эмулятора.
    """

    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    def __init__(self):
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

        self._create_table()
        logger.debug("✅ MailStorage инициализирован")

    def _create_table(self):
        """Создать таблицу если не существует"""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS mail_rewards_log (
                    emulator_id INTEGER PRIMARY KEY,
                    last_collected_at TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._conn.commit()

    # ==================== ЧТЕНИЕ ====================

    def get_last_collected(self, emulator_id: int) -> Optional[datetime]:
        """
        Получить время последнего сбора наград.

        Args:
            emulator_id: ID эмулятора

        Returns:
            datetime или None (если записи нет)
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT last_collected_at FROM mail_rewards_log "
                "WHERE emulator_id = ?",
                (emulator_id,)
            )
            row = cursor.fetchone()

            if row is None or row['last_collected_at'] is None:
                return None

            return datetime.fromisoformat(row['last_collected_at'])

    def has_data(self, emulator_id: int) -> bool:
        """
        Есть ли запись для эмулятора в БД?

        Args:
            emulator_id: ID эмулятора

        Returns:
            True если запись существует
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT 1 FROM mail_rewards_log WHERE emulator_id = ?",
                (emulator_id,)
            )
            return cursor.fetchone() is not None

    def is_overdue(self, emulator_id: int) -> bool:
        """
        Просрочен ли сбор (> 48 часов)?

        Args:
            emulator_id: ID эмулятора

        Returns:
            True если последний сбор был > 48ч назад
            False если нет записи или сбор свежий
        """
        last = self.get_last_collected(emulator_id)

        if last is None:
            return False  # Нет записи → ждём первую сессию wilds

        return datetime.now() - last > timedelta(hours=SELF_TRIGGER_HOURS)

    # ==================== ЗАПИСЬ ====================

    def update_collected(self, emulator_id: int):
        """
        Обновить время последнего сбора наград.

        INSERT OR REPLACE — создаёт запись если нет,
        обновляет если есть.

        Args:
            emulator_id: ID эмулятора
        """
        now = datetime.now().isoformat()

        with self._lock:
            self._conn.execute("""
                INSERT INTO mail_rewards_log
                    (emulator_id, last_collected_at, last_updated)
                VALUES (?, ?, ?)
                ON CONFLICT(emulator_id) DO UPDATE SET
                    last_collected_at = excluded.last_collected_at,
                    last_updated = excluded.last_updated
            """, (emulator_id, now, now))
            self._conn.commit()

        logger.debug(
            f"📬 MailStorage: обновлено last_collected_at "
            f"для emu_id={emulator_id}"
        )

    # ==================== УДАЛЕНИЕ ====================

    def delete_emulator(self, emulator_id: int):
        """
        Удалить данные эмулятора.

        Args:
            emulator_id: ID эмулятора
        """
        with self._lock:
            self._conn.execute(
                "DELETE FROM mail_rewards_log WHERE emulator_id = ?",
                (emulator_id,)
            )
            self._conn.commit()

        logger.debug(
            f"📬 MailStorage: удалены данные для emu_id={emulator_id}"
        )