"""
Хранилище прогресса ДС (ds_progress)

Таблица в общей bot.db:
  emulator_id   — ID эмулятора
  event_key     — уникальный ключ ДС ('mon_06', 'sun_03')
  target_minutes— сколько минут ускорений нужно потратить
  spent_minutes — сколько уже потрачено
  target_shell  — какую ракушку целимся (1 или 2)
  status        — 'in_progress' / 'completed' / 'skipped'
  skip_reason   — причина пропуска (NULL если нет)

Назначение:
  - Восстановление после краша (сколько уже потрачено)
  - Предотвращение повторной траты при перезапуске эмулятора

Thread-safe через RLock.

Версия: 1.0
"""

import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional, Dict

from utils.logger import logger

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class PrimeStorage:
    """
    CRUD для таблицы ds_progress в bot.db

    Хранит прогресс траты ускорений для каждого ДС
    на каждом эмуляторе.
    """

    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    def __init__(self):
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

        self._create_table()
        logger.debug("✅ PrimeStorage инициализирован")

    def _create_table(self):
        """Создать таблицу если не существует"""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS ds_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    event_key TEXT NOT NULL,
                    target_minutes INTEGER NOT NULL,
                    spent_minutes INTEGER DEFAULT 0,
                    target_shell INTEGER DEFAULT 2,
                    status TEXT DEFAULT 'in_progress',
                    skip_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(emulator_id, event_key)
                )
            """)
            self._conn.commit()

    # ==================== ЧТЕНИЕ ====================

    def get_progress(
        self,
        emulator_id: int,
        event_key: str
    ) -> Optional[Dict]:
        """
        Получить прогресс ДС для эмулятора.

        Args:
            emulator_id: ID эмулятора
            event_key: ключ ДС ('mon_06', 'sun_03')

        Returns:
            {
                'emulator_id': int,
                'event_key': str,
                'target_minutes': int,
                'spent_minutes': int,
                'target_shell': int,
                'status': str,
                'skip_reason': str | None,
                'created_at': str,
                'updated_at': str,
            }
            или None если записи нет
        """
        if emulator_id is None:
            return None

        with self._lock:
            cursor = self._conn.execute("""
                SELECT emulator_id, event_key, target_minutes,
                       spent_minutes, target_shell, status,
                       skip_reason, created_at, updated_at
                FROM ds_progress
                WHERE emulator_id = ? AND event_key = ?
            """, (emulator_id, event_key))

            row = cursor.fetchone()

        if row is None:
            return None

        return dict(row)

    def is_completed(self, emulator_id: int, event_key: str) -> bool:
        """
        Завершён ли ДС для эмулятора?

        Returns:
            True если status = 'completed' или 'skipped'
        """
        progress = self.get_progress(emulator_id, event_key)
        if progress is None:
            return False

        return progress['status'] in ('completed', 'skipped')

    # ==================== ЗАПИСЬ ====================

    def save_progress(
        self,
        emulator_id: int,
        event_key: str,
        target_minutes: int,
        spent_minutes: int = 0,
        target_shell: int = 2,
        status: str = 'in_progress'
    ):
        """
        Создать или обновить запись прогресса.

        Использует INSERT OR REPLACE (UPSERT по UNIQUE constraint).

        Args:
            emulator_id: ID эмулятора
            event_key: ключ ДС
            target_minutes: целевые минуты
            spent_minutes: уже потрачено
            target_shell: целевая ракушка (1 или 2)
            status: статус
        """
        if emulator_id is None:
            logger.error("❌ PrimeStorage.save_progress: emulator_id is None")
            return

        now = datetime.now().isoformat()

        with self._lock:
            self._conn.execute("""
                INSERT INTO ds_progress 
                    (emulator_id, event_key, target_minutes,
                     spent_minutes, target_shell, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(emulator_id, event_key) DO UPDATE SET
                    target_minutes = excluded.target_minutes,
                    spent_minutes = excluded.spent_minutes,
                    target_shell = excluded.target_shell,
                    status = excluded.status,
                    updated_at = excluded.updated_at
            """, (
                emulator_id, event_key, target_minutes,
                spent_minutes, target_shell, status, now
            ))
            self._conn.commit()

        logger.debug(
            f"[Emulator {emulator_id}] 💾 ds_progress: "
            f"{event_key} → {spent_minutes}/{target_minutes} мин "
            f"(shell={target_shell}, status={status})"
        )

    def add_spent_minutes(
        self,
        emulator_id: int,
        event_key: str,
        minutes: int
    ) -> int:
        """
        Инкрементально добавить потраченные минуты.

        Args:
            emulator_id: ID эмулятора
            event_key: ключ ДС
            minutes: сколько минут добавить

        Returns:
            Новое суммарное значение spent_minutes.
            -1 если записи нет.
        """
        if emulator_id is None:
            return -1

        now = datetime.now().isoformat()

        with self._lock:
            cursor = self._conn.execute("""
                UPDATE ds_progress
                SET spent_minutes = spent_minutes + ?,
                    updated_at = ?
                WHERE emulator_id = ? AND event_key = ?
            """, (minutes, now, emulator_id, event_key))

            if cursor.rowcount == 0:
                logger.warning(
                    f"[Emulator {emulator_id}] ⚠️ ds_progress: "
                    f"запись {event_key} не найдена для add_spent_minutes"
                )
                return -1

            # Читаем новое значение
            cursor = self._conn.execute("""
                SELECT spent_minutes FROM ds_progress
                WHERE emulator_id = ? AND event_key = ?
            """, (emulator_id, event_key))

            row = cursor.fetchone()
            self._conn.commit()

        new_total = row['spent_minutes'] if row else -1

        logger.debug(
            f"[Emulator {emulator_id}] ⏱️ ds_progress: "
            f"{event_key} +{minutes} мин → {new_total} мин"
        )

        return new_total

    def mark_completed(self, emulator_id: int, event_key: str):
        """Пометить ДС как завершённый."""
        self._update_status(emulator_id, event_key, 'completed')

    def mark_skipped(
        self,
        emulator_id: int,
        event_key: str,
        reason: str
    ):
        """
        Пометить ДС как пропущенный.

        Args:
            emulator_id: ID эмулятора
            event_key: ключ ДС
            reason: причина ('not_enough_speedups', '>65h', 'no_time', ...)
        """
        if emulator_id is None:
            return

        now = datetime.now().isoformat()

        with self._lock:
            # Сначала пробуем update
            cursor = self._conn.execute("""
                UPDATE ds_progress
                SET status = 'skipped', skip_reason = ?, updated_at = ?
                WHERE emulator_id = ? AND event_key = ?
            """, (reason, now, emulator_id, event_key))

            # Если записи нет — создаём
            if cursor.rowcount == 0:
                self._conn.execute("""
                    INSERT INTO ds_progress
                        (emulator_id, event_key, target_minutes,
                         spent_minutes, target_shell, status,
                         skip_reason, updated_at)
                    VALUES (?, ?, 0, 0, 0, 'skipped', ?, ?)
                """, (emulator_id, event_key, reason, now))

            self._conn.commit()

        logger.info(
            f"[Emulator {emulator_id}] ⏭️ ДС {event_key} пропущен: {reason}"
        )

    # ==================== УТИЛИТЫ ====================

    def get_all_for_emulator(
        self,
        emulator_id: int
    ) -> list:
        """
        Все записи ДС для эмулятора (для отладки / GUI).

        Returns:
            Список dict, отсортированный по updated_at DESC
        """
        if emulator_id is None:
            return []

        with self._lock:
            cursor = self._conn.execute("""
                SELECT emulator_id, event_key, target_minutes,
                       spent_minutes, target_shell, status,
                       skip_reason, created_at, updated_at
                FROM ds_progress
                WHERE emulator_id = ?
                ORDER BY updated_at DESC
            """, (emulator_id,))

            rows = cursor.fetchall()

        return [dict(r) for r in rows]

    def delete_for_emulator(self, emulator_id: int) -> int:
        """
        Удалить все записи ДС для эмулятора.

        Используется при полном сбросе данных эмулятора.

        Returns:
            Количество удалённых записей
        """
        if emulator_id is None:
            return 0

        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM ds_progress WHERE emulator_id = ?",
                (emulator_id,)
            )
            self._conn.commit()

        count = cursor.rowcount
        if count > 0:
            logger.info(
                f"[Emulator {emulator_id}] 🗑️ Удалено {count} записей ds_progress"
            )
        return count

    def cleanup_old(self, days: int = 7) -> int:
        """
        Удалить записи старше N дней.

        Для предотвращения неограниченного роста таблицы.

        Args:
            days: порог в днях

        Returns:
            Количество удалённых записей
        """
        cutoff = (
            datetime.now() - __import__('datetime').timedelta(days=days)
        ).isoformat()

        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM ds_progress WHERE updated_at < ?",
                (cutoff,)
            )
            self._conn.commit()

        count = cursor.rowcount
        if count > 0:
            logger.info(f"🧹 ds_progress: удалено {count} старых записей (>{days}д)")
        return count

    def close(self):
        """Закрыть соединение с БД"""
        try:
            self._conn.close()
        except Exception:
            pass

    # ==================== ПРИВАТНЫЕ ====================

    def _update_status(
        self,
        emulator_id: int,
        event_key: str,
        status: str
    ):
        """Обновить статус записи."""
        if emulator_id is None:
            return

        now = datetime.now().isoformat()

        with self._lock:
            cursor = self._conn.execute("""
                UPDATE ds_progress
                SET status = ?, updated_at = ?
                WHERE emulator_id = ? AND event_key = ?
            """, (status, now, emulator_id, event_key))
            self._conn.commit()

        if cursor.rowcount == 0:
            logger.warning(
                f"[Emulator {emulator_id}] ⚠️ ds_progress: "
                f"запись {event_key} не найдена для статуса '{status}'"
            )
        else:
            logger.info(
                f"[Emulator {emulator_id}] ✅ ДС {event_key} → {status}"
            )