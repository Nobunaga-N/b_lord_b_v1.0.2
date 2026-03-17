"""
Распределение отрядов по ресурсам для плиток

Алгоритм:
1. Обычный день:
   - Дефицит (<70%) → отряды поровну между дефицитными ресурсами
   - Нет дефицита → поровну между всеми ресурсами (<97%)
   - Все >97% → не отправлять
2. Вторник (weekday=1):
   - Обязательно посетить все 4 типа ресурсов (за одну или несколько сессий)
   - Трекинг посещённых ресурсов через БД
3. Суббота (weekday=5):
   - Ходить даже если склады полные
4. Воскресенье (weekday=6):
   - Обрабатывается в can_execute(), сюда не попадает
5. Среда (weekday=2):
   - Если во вторник не все ресурсы посещены → обязательно сходить на пропущенные

Приоритет при нечётном распределении: песок > грунт > листья > яблоки

Версия: 1.0
Дата создания: 2025-03-17
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from utils.logger import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Приоритет ресурсов (от высокого к низкому)
RESOURCE_PRIORITY = ['sand', 'soil', 'leaves', 'apples']

# Все доступные ресурсы на плитках (без мёда)
ALL_TILE_RESOURCES = ['apples', 'leaves', 'soil', 'sand']

# Пороги
DEFICIT_THRESHOLD = 70   # Ниже этого — дефицитный ресурс (%)
FULL_THRESHOLD = 97      # Выше этого — склад полный, не отправлять (%)

# Русские названия для логов
RESOURCE_NAMES_RU = {
    'apples': 'Яблоки',
    'leaves': 'Листья',
    'soil': 'Грунт',
    'sand': 'Песок',
}


class TilesDistributor:
    """
    Распределяет отряды по ресурсам для сбора с плиток

    Использование:
        distributor = TilesDistributor()
        assignments = distributor.distribute(
            storage_data={'sand': {'fill_pct': 45.0}, ...},
            enabled_squads=['special', 'squad_1'],
            enabled_resources=['apples', 'leaves', 'soil', 'sand'],
            day_of_week=1,  # вторник
            emulator_id=0
        )
        # → [{'squad_key': 'special', 'resource': 'sand'},
        #    {'squad_key': 'squad_1', 'resource': 'soil'}]
    """

    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    def __init__(self):
        self._lock = threading.RLock()
        self._ensure_table()

    # ==================== ГЛАВНЫЙ МЕТОД ====================

    def distribute(
        self,
        storage_data: Dict,
        enabled_squads: List[str],
        enabled_resources: List[str],
        day_of_week: int,
        emulator_id: int
    ) -> List[Dict]:
        """
        Распределить отряды по ресурсам

        Args:
            storage_data: {resource: {'stored': float, 'capacity': float, 'fill_pct': float}}
            enabled_squads: ['special', 'squad_1', ...]
            enabled_resources: ['apples', 'leaves', 'soil', 'sand']
            day_of_week: 0=пн, 1=вт, 2=ср, ..., 6=вс
            emulator_id: ID эмулятора (для трекинга вторника)

        Returns:
            [{'squad_key': str, 'resource': str}, ...]
            Пустой список если не нужно отправлять
        """
        if not enabled_squads or not enabled_resources:
            return []

        # Фильтруем ресурсы: только те что есть и в enabled, и в storage_data
        # (или в enabled для вторника/субботы без storage_data)
        available = [r for r in enabled_resources if r in ALL_TILE_RESOURCES]
        if not available:
            return []

        num_squads = len(enabled_squads)

        # === ВТОРНИК: обязательно все 4 ресурса ===
        if day_of_week == 1:
            return self._distribute_tuesday(
                storage_data, enabled_squads, available, emulator_id
            )

        # === СРЕДА: проверить вторничный трекинг ===
        if day_of_week == 2:
            unvisited = self._get_tuesday_unvisited(available, emulator_id)
            if unvisited:
                return self._distribute_forced(
                    enabled_squads, unvisited, emulator_id,
                    reason="среда: довизит вторничных ресурсов"
                )

        # === СУББОТА: ходить даже если полные ===
        if day_of_week == 5:
            target_resources = self._pick_resources_by_priority(
                storage_data, available, num_squads,
                ignore_full=True
            )
            if not target_resources:
                # Все ресурсы выключены — не должно случиться, fallback
                target_resources = available[:num_squads]
            return self._assign_squads(enabled_squads, target_resources)

        # === ОБЫЧНЫЙ ДЕНЬ ===
        target_resources = self._pick_resources_by_priority(
            storage_data, available, num_squads,
            ignore_full=False
        )

        if not target_resources:
            logger.info("📦 Все склады >97% — плитки не нужны")
            return []

        return self._assign_squads(enabled_squads, target_resources)

    # ==================== ЛОГИКА ОБЫЧНОГО ДНЯ ====================

    def _pick_resources_by_priority(
        self,
        storage_data: Dict,
        available: List[str],
        num_squads: int,
        ignore_full: bool = False
    ) -> List[str]:
        """
        Выбрать ресурсы для отправки отрядов

        Алгоритм:
        1. Отфильтровать полные (>97%), если не ignore_full
        2. Если есть дефицитные (<70%) → только они
        3. Иначе → все доступные
        4. Распределить num_squads поровну по приоритету

        Returns:
            Список ресурсов длиной num_squads (или меньше)
        """
        # Фильтрация полных
        if ignore_full:
            candidates = available[:]
        else:
            candidates = []
            for res in available:
                data = storage_data.get(res)
                if data is None:
                    # Нет данных — включаем на всякий случай
                    candidates.append(res)
                elif data['fill_pct'] <= FULL_THRESHOLD:
                    candidates.append(res)

        if not candidates:
            return []

        # Разделяем на дефицитные и остальные
        deficit = []
        normal = []

        for res in candidates:
            data = storage_data.get(res)
            if data is None:
                normal.append(res)
            elif data['fill_pct'] < DEFICIT_THRESHOLD:
                deficit.append(res)
            else:
                normal.append(res)

        # Выбор пула
        if deficit:
            pool = deficit
        else:
            pool = candidates

        # Сортировка по приоритету
        pool_sorted = sorted(pool, key=lambda r: (
            RESOURCE_PRIORITY.index(r)
            if r in RESOURCE_PRIORITY else 99
        ))

        # Распределение: поровну, лишние по приоритету
        return self._spread_squads_over_resources(pool_sorted, num_squads)

    @staticmethod
    def _spread_squads_over_resources(
        resources: List[str],
        num_squads: int
    ) -> List[str]:
        """
        Распределить num_squads поровну по resources

        Пример: resources=['sand','soil','leaves'], num_squads=5
        → ['sand','sand','soil','soil','leaves']

        Пример: resources=['sand','soil'], num_squads=3
        → ['sand','sand','soil']  (лишний → приоритетному)

        Returns:
            Список ресурсов длиной num_squads
        """
        if not resources:
            return []

        result = []
        n_res = len(resources)

        # Базовое кол-во на каждый ресурс
        base = num_squads // n_res
        remainder = num_squads % n_res

        for i, res in enumerate(resources):
            count = base + (1 if i < remainder else 0)
            result.extend([res] * count)

        return result[:num_squads]

    # ==================== ВТОРНИК ====================

    def _distribute_tuesday(
        self,
        storage_data: Dict,
        enabled_squads: List[str],
        available: List[str],
        emulator_id: int
    ) -> List[Dict]:
        """
        Вторник: обязательно посетить все 4 ресурса

        Если отрядов < 4: выбрать ещё не посещённые в первую очередь
        """
        already_visited = self._load_tuesday_visited(emulator_id)
        unvisited = [r for r in available if r not in already_visited]

        if not unvisited:
            # Все уже посещены — обычное распределение (суббота-стиль)
            target_resources = self._pick_resources_by_priority(
                storage_data, available, len(enabled_squads),
                ignore_full=True
            )
            if not target_resources:
                target_resources = available[:len(enabled_squads)]
            return self._assign_squads(enabled_squads, target_resources)

        num_squads = len(enabled_squads)

        if num_squads >= len(unvisited):
            # Хватает отрядов на все непосещённые
            target = list(unvisited)
            # Остаток — по приоритету из всех
            remaining_slots = num_squads - len(target)
            if remaining_slots > 0:
                extras = self._pick_resources_by_priority(
                    storage_data, available, remaining_slots,
                    ignore_full=True
                )
                target.extend(extras)
        else:
            # Отрядов меньше чем непосещённых — берём по приоритету
            sorted_unvisited = sorted(unvisited, key=lambda r: (
                RESOURCE_PRIORITY.index(r)
                if r in RESOURCE_PRIORITY else 99
            ))
            target = sorted_unvisited[:num_squads]

        assignments = self._assign_squads(enabled_squads, target)

        # Записать посещённые ресурсы
        visited_now = [a['resource'] for a in assignments]
        self._save_tuesday_visited(emulator_id, already_visited + visited_now)

        return assignments

    # ==================== СРЕДА: ДОВИЗИТ ====================

    def _get_tuesday_unvisited(
        self,
        available: List[str],
        emulator_id: int
    ) -> List[str]:
        """
        Получить ресурсы, не посещённые во вторник

        Returns:
            Список непосещённых ресурсов (пустой если все посещены
            или если вторничных данных нет)
        """
        visited = self._load_tuesday_visited(emulator_id)

        if not visited:
            # Нет данных вторника — ничего не делаем
            return []

        unvisited = [r for r in available if r not in visited]
        return unvisited

    def _distribute_forced(
        self,
        enabled_squads: List[str],
        forced_resources: List[str],
        emulator_id: int,
        reason: str = ""
    ) -> List[Dict]:
        """
        Принудительное распределение на конкретные ресурсы

        Используется для среды (довизит вторничных ресурсов)
        """
        num_squads = len(enabled_squads)
        target = self._spread_squads_over_resources(
            forced_resources, num_squads
        )

        if reason:
            logger.info(f"🗺 Плитки ({reason}): {target}")

        assignments = self._assign_squads(enabled_squads, target)

        # Обновить трекинг вторника
        visited = self._load_tuesday_visited(emulator_id)
        visited_now = [a['resource'] for a in assignments]
        self._save_tuesday_visited(emulator_id, visited + visited_now)

        return assignments

    # ==================== НАЗНАЧЕНИЕ ОТРЯДОВ ====================

    @staticmethod
    def _assign_squads(
        enabled_squads: List[str],
        target_resources: List[str]
    ) -> List[Dict]:
        """
        Привязать отряды к ресурсам

        Args:
            enabled_squads: ['special', 'squad_1', ...]
            target_resources: ['sand', 'sand', 'soil'] — длина == len(enabled_squads)

        Returns:
            [{'squad_key': 'special', 'resource': 'sand'}, ...]
        """
        assignments = []
        for i, squad_key in enumerate(enabled_squads):
            if i < len(target_resources):
                assignments.append({
                    'squad_key': squad_key,
                    'resource': target_resources[i],
                })
        return assignments

    # ==================== ТРЕКИНГ ВТОРНИКА (БД) ====================

    def _ensure_table(self):
        """Создать таблицу для трекинга вторника"""
        try:
            os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)
            conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tiles_tuesday_tracking (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        emulator_id INTEGER NOT NULL,
                        week_start TEXT NOT NULL,
                        visited_resources TEXT NOT NULL DEFAULT '',
                        UNIQUE(emulator_id, week_start)
                    )
                """)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"❌ Не удалось создать таблицу tiles_tuesday_tracking: {e}")

    def _get_week_key(self) -> str:
        """
        Ключ текущей недели (ISO формат понедельника)

        Нужен чтобы трекинг вторника не смешивался между неделями
        """
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()

    def _load_tuesday_visited(self, emulator_id: int) -> List[str]:
        """Загрузить посещённые ресурсы вторника из БД"""
        week_key = self._get_week_key()
        try:
            with self._lock:
                conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                try:
                    cursor = conn.execute("""
                        SELECT visited_resources FROM tiles_tuesday_tracking
                        WHERE emulator_id = ? AND week_start = ?
                    """, (emulator_id, week_key))
                    row = cursor.fetchone()
                    if row and row['visited_resources']:
                        return row['visited_resources'].split(',')
                    return []
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки tiles_tuesday_tracking: {e}")
            return []

    def _save_tuesday_visited(self, emulator_id: int, visited: List[str]):
        """Сохранить посещённые ресурсы вторника в БД"""
        week_key = self._get_week_key()
        # Дедупликация
        unique = list(dict.fromkeys(visited))
        value = ','.join(unique)

        try:
            with self._lock:
                conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
                try:
                    conn.execute("""
                        INSERT INTO tiles_tuesday_tracking
                            (emulator_id, week_start, visited_resources)
                        VALUES (?, ?, ?)
                        ON CONFLICT(emulator_id, week_start)
                        DO UPDATE SET visited_resources = ?
                    """, (emulator_id, week_key, value, value))
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения tiles_tuesday_tracking: {e}")

    def clear_tuesday_tracking(self, emulator_id: int):
        """Очистить трекинг вторника (для тестов/сброса)"""
        try:
            with self._lock:
                conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
                try:
                    conn.execute("""
                        DELETE FROM tiles_tuesday_tracking
                        WHERE emulator_id = ?
                    """, (emulator_id,))
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"❌ Ошибка очистки tiles_tuesday_tracking: {e}")