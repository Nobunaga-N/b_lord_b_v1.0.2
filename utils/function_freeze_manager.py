"""
Менеджер заморозки функций при критических ошибках

ЕДИНСТВЕННЫЙ источник правды для заморозок.
Хранит данные в SQLite (переживает перезапуск) + кеш в памяти (быстрый доступ).

При критической ошибке в функции — замораживает её на указанное время
для конкретного эмулятора. Остальные функции продолжают работать.

Версия: 2.0
Дата обновления: 2025-02-19
Изменения:
- Добавлена SQLite persistence (заморозки переживают перезапуск)
- Хранение причины заморозки
- Загрузка активных заморозок при инициализации
- Единый источник правды (building_database и evolution_database делегируют сюда)
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from utils.logger import logger

# Базовая директория проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FunctionFreezeManager:
    """
    Менеджер заморозки функций

    In-memory кеш: {(emulator_id, function_name): (unfreeze_datetime, reason)}
    SQLite таблица: function_freeze (emulator_id, function_name, freeze_until, reason)
    Thread-safe через RLock.

    Все операции пишут и в память, и в SQLite одновременно.
    При старте бота — загружает активные заморозки из SQLite в кеш.
    """

    DEFAULT_FREEZE_HOURS = 4
    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    def __init__(self):
        self._freezes: Dict[tuple, Tuple[datetime, str]] = {}
        self._lock = threading.RLock()

        # Инициализация БД
        self._ensure_table()

        # Загрузить активные заморозки из SQLite
        self._load_from_db()

    # ===== ИНИЦИАЛИЗАЦИЯ БД =====

    def _ensure_table(self):
        """Создать таблицу если не существует"""
        try:
            os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)
            conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS function_freeze (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        emulator_id INTEGER NOT NULL,
                        function_name TEXT NOT NULL,
                        freeze_until TIMESTAMP NOT NULL,
                        reason TEXT,
                        UNIQUE(emulator_id, function_name)
                    )
                """)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"❌ Не удалось создать таблицу function_freeze: {e}")

    def _load_from_db(self):
        """Загрузить активные заморозки из SQLite в кеш"""
        try:
            conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                now = datetime.now()

                # Удалить истёкшие
                cursor.execute(
                    "DELETE FROM function_freeze WHERE freeze_until <= ?",
                    (now,)
                )
                conn.commit()

                # Загрузить активные
                cursor.execute(
                    "SELECT emulator_id, function_name, freeze_until, reason "
                    "FROM function_freeze"
                )
                rows = cursor.fetchall()

                with self._lock:
                    for row in rows:
                        freeze_until = row['freeze_until']
                        if isinstance(freeze_until, str):
                            freeze_until = datetime.fromisoformat(freeze_until)

                        key = (row['emulator_id'], row['function_name'])
                        reason = row['reason'] or ""
                        self._freezes[key] = (freeze_until, reason)

                if rows:
                    logger.info(
                        f"🧊 Загружено {len(rows)} активных заморозок из БД"
                    )
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки заморозок из БД: {e}")

    # ===== ЗАПИСЬ В БД =====

    def _save_to_db(self, emulator_id: int, function_name: str,
                    freeze_until: datetime, reason: str):
        """Сохранить заморозку в SQLite"""
        try:
            conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO function_freeze 
                    (emulator_id, function_name, freeze_until, reason)
                    VALUES (?, ?, ?, ?)
                """, (emulator_id, function_name, freeze_until, reason))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(
                f"❌ Ошибка сохранения заморозки в БД: {e}"
            )

    def _delete_from_db(self, emulator_id: int, function_name: str):
        """Удалить заморозку из SQLite"""
        try:
            conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            try:
                conn.execute("""
                    DELETE FROM function_freeze 
                    WHERE emulator_id = ? AND function_name = ?
                """, (emulator_id, function_name))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(
                f"❌ Ошибка удаления заморозки из БД: {e}"
            )

    def _delete_all_from_db(self, emulator_id: int = None):
        """Удалить все заморозки из SQLite (или для конкретного эмулятора)"""
        try:
            conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            try:
                if emulator_id is not None:
                    conn.execute(
                        "DELETE FROM function_freeze WHERE emulator_id = ?",
                        (emulator_id,)
                    )
                else:
                    conn.execute("DELETE FROM function_freeze")
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"❌ Ошибка очистки заморозок в БД: {e}")

    # ===== ОСНОВНЫЕ МЕТОДЫ =====

    def freeze(self, emulator_id: int, function_name: str,
               hours: float = None, reason: str = ""):
        """
        Заморозить функцию для эмулятора

        Пишет одновременно в in-memory кеш и SQLite.

        Args:
            emulator_id: ID эмулятора
            function_name: имя функции (building, research, и т.д.)
            hours: на сколько часов заморозить (по умолчанию 4)
            reason: причина заморозки (для лога и GUI)
        """
        hours = hours or self.DEFAULT_FREEZE_HOURS
        key = (emulator_id, function_name)
        unfreeze_at = datetime.now() + timedelta(hours=hours)

        # In-memory
        with self._lock:
            self._freezes[key] = (unfreeze_at, reason)

        # SQLite
        self._save_to_db(emulator_id, function_name, unfreeze_at, reason)

        logger.warning(
            f"🧊 Функция '{function_name}' заморожена для эмулятора "
            f"{emulator_id} на {hours}ч "
            f"(до {unfreeze_at.strftime('%H:%M:%S')}). "
            f"Причина: {reason}"
        )

    def is_frozen(self, emulator_id: int, function_name: str) -> bool:
        """
        Проверить заморожена ли функция

        Проверяет только in-memory кеш (быстро).
        Автоматически разморозит если время вышло.

        Returns:
            True если функция заморожена
        """
        key = (emulator_id, function_name)

        with self._lock:
            if key not in self._freezes:
                return False

            unfreeze_at, reason = self._freezes[key]

            if datetime.now() >= unfreeze_at:
                # Время вышло — разморозить
                del self._freezes[key]
                # Чистим SQLite в фоне
                self._delete_from_db(emulator_id, function_name)
                logger.info(
                    f"🔓 Функция '{function_name}' автоматически "
                    f"разморожена для эмулятора {emulator_id}"
                )
                return False

            return True

    def get_unfreeze_time(self, emulator_id: int,
                          function_name: str) -> Optional[datetime]:
        """Получить время разморозки (или None если не заморожена)"""
        key = (emulator_id, function_name)
        with self._lock:
            data = self._freezes.get(key)
            return data[0] if data else None

    def get_freeze_reason(self, emulator_id: int,
                          function_name: str) -> Optional[str]:
        """Получить причину заморозки (или None)"""
        key = (emulator_id, function_name)
        with self._lock:
            data = self._freezes.get(key)
            return data[1] if data else None

    def get_frozen_functions(self, emulator_id: int) -> List[str]:
        """Получить список замороженных функций для эмулятора"""
        now = datetime.now()
        result = []
        expired_keys = []

        with self._lock:
            for (emu_id, func_name), (unfreeze_at, _) in list(
                    self._freezes.items()):
                if emu_id == emulator_id:
                    if now >= unfreeze_at:
                        expired_keys.append((emu_id, func_name))
                    else:
                        result.append(func_name)

            # Очистить истёкшие
            for key in expired_keys:
                del self._freezes[key]

        # Чистим SQLite для истёкших
        for emu_id, func_name in expired_keys:
            self._delete_from_db(emu_id, func_name)

        return result

    def unfreeze(self, emulator_id: int, function_name: str):
        """Принудительно разморозить функцию (из GUI или кода)"""
        key = (emulator_id, function_name)
        removed = False

        with self._lock:
            if key in self._freezes:
                del self._freezes[key]
                removed = True

        if removed:
            self._delete_from_db(emulator_id, function_name)
            logger.info(
                f"🔓 Функция '{function_name}' принудительно "
                f"разморожена для эмулятора {emulator_id}"
            )

    def unfreeze_all(self, emulator_id: int = None):
        """
        Разморозить все функции

        Args:
            emulator_id: если указан — только для этого эмулятора,
                         если None — для всех эмуляторов
        """
        with self._lock:
            if emulator_id is not None:
                keys_to_remove = [
                    k for k in self._freezes if k[0] == emulator_id
                ]
            else:
                keys_to_remove = list(self._freezes.keys())

            for key in keys_to_remove:
                del self._freezes[key]

        self._delete_all_from_db(emulator_id)

        target = f"эмулятора {emulator_id}" if emulator_id else "ВСЕХ"
        logger.info(
            f"🔓 Все функции разморожены для {target} "
            f"({len(keys_to_remove)} шт.)"
        )

    def get_all_freezes(self) -> Dict[tuple, Tuple[datetime, str]]:
        """
        Получить все активные заморозки

        Returns:
            {(emulator_id, function_name): (unfreeze_at, reason)}
        """
        now = datetime.now()
        expired_keys = []

        with self._lock:
            # Найти истёкшие
            for key, (unfreeze_at, _) in list(self._freezes.items()):
                if now >= unfreeze_at:
                    expired_keys.append(key)

            # Удалить истёкшие
            for key in expired_keys:
                del self._freezes[key]

            result = dict(self._freezes)

        # Чистим SQLite для истёкших
        for emu_id, func_name in expired_keys:
            self._delete_from_db(emu_id, func_name)

        return result


# Глобальный экземпляр (создаётся при первом импорте)
function_freeze_manager = FunctionFreezeManager()