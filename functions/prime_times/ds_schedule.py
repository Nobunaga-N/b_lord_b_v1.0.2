"""
Расписание Действий Стаи (ДС) — хардкод UTC+3

Чистый Python, ноль зависимостей от ADB/OCR/БД.

Расписание хранится как плоский словарь {(weekday, hour): (type, points_per_min)},
где weekday — ФИЗИЧЕСКИЙ день (datetime.weekday(): Mon=0..Sun=6),
hour — ФИЗИЧЕСКИЙ час (0-23) по UTC+3.

Звёздочные события из расписания (00:00*, 01:00*, 02:00*) транслируются
в физические координаты следующего дня при инициализации.

Окно ДС: 55 минут
  :00:00 — :04:59  неактивно (обновление)
  :05:00 — :59:59  активно

API:
  get_current_event(now)           → текущий активный ДС или None
  get_next_event(now)              → ближайший будущий ДС
  is_safe_to_start(now, min_min)   → безопасно ли начинать drain
  get_allowed_speedup_types(type)  → допустимые типы ускорений

Версия: 1.0
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, List

from utils.logger import logger


# ═══════════════════════════════════════════════════
# КОНСТАНТЫ
# ═══════════════════════════════════════════════════

# Окно ДС
DS_ACTIVE_START_MINUTE = 5   # ДС активен с :05:00
DS_ACTIVE_END_MINUTE = 59    # ДС активен до :59:59
DS_DURATION_MINUTES = 55     # длительность активного окна

# Короткие имена дней (для event_key)
DAY_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


# ═══════════════════════════════════════════════════
# РАСПИСАНИЕ (ИСХОДНЫЕ ДАННЫЕ ПО ИГРОВЫМ ДНЯМ)
# ═══════════════════════════════════════════════════
#
# Формат: {игровой_день: [(час, тип, очки_за_мин, is_next_day), ...]}
# is_next_day=True → звёздочное событие (физически следующий день)
#
# Игровые дни: 0=Monday .. 6=Sunday

_RAW_SCHEDULE = {
    # ── Понедельник ──
    0: [
        (6,  'any', 400, False),
        (14, 'any', 400, False),
        (22, 'any', 400, False),
    ],

    # ── Вторник ──
    1: [
        (5,  'training', 400, False),
        (7,  'training+evolution+building', 400, False),
        (8,  'training', 400, False),
        (13, 'training', 400, False),
        (15, 'training+evolution+building', 400, False),
        (16, 'training', 400, False),
        (21, 'training', 400, False),
        (23, 'training+evolution+building', 400, False),
        (0,  'training', 400, True),  # 00:00* → среда физ.
    ],

    # ── Среда ──
    2: [
        (5,  'training', 400, False),
        (8,  'training+evolution+building', 400, False),
        (9,  'training', 400, False),
        (10, 'training+evolution+building', 400, False),
        (13, 'training', 400, False),
        (16, 'training+evolution+building', 400, False),
        (17, 'training', 400, False),
        (18, 'training+evolution+building', 400, False),
        (21, 'training', 400, False),
        (0,  'training+evolution+building', 400, True),  # 00:00*
        (1,  'training', 400, True),                      # 01:00*
        (2,  'training+evolution+building', 400, True),   # 02:00*
    ],

    # ── Четверг ──
    3: [
        (5,  'training+evolution+building', 400, False),
        (7,  'training+evolution+building', 400, False),
        (9,  'training', 400, False),
        (13, 'training+evolution+building', 400, False),
        (15, 'training+evolution+building', 400, False),
        (17, 'training', 400, False),
        (21, 'training+evolution+building', 400, False),
        (23, 'training+evolution+building', 400, False),
        (1,  'training', 400, True),  # 01:00*
    ],

    # ── Пятница ──
    4: [
        (3,  'training+evolution+building', 400, False),
        (4,  'training+evolution+building', 400, False),
        (5,  'training', 400, False),
        (6,  'training', 400, False),
        (7,  'training', 400, False),
        (10, 'training+evolution+building', 400, False),
        (11, 'training+evolution+building', 400, False),
        (12, 'training+evolution+building', 400, False),
        (13, 'training', 400, False),
        (14, 'training', 400, False),
        (15, 'training', 400, False),
        (18, 'training+evolution+building', 400, False),
        (19, 'training+evolution+building', 400, False),
        (20, 'training+evolution+building', 400, False),
        (21, 'training', 400, False),
        (22, 'training', 400, False),
        (23, 'training', 400, False),
        (2,  'training+evolution+building', 400, True),  # 02:00*
    ],

    # ── Суббота ──
    5: [
        (3,  'training+evolution+building', 400, False),
        (6,  'training', 400, False),
        (7,  'training', 400, False),
        (8,  'training', 400, False),
        (11, 'training+evolution+building', 400, False),
        (14, 'training', 400, False),
        (15, 'training', 400, False),
        (16, 'training', 400, False),
        (19, 'training+evolution+building', 400, False),
        (22, 'training', 400, False),
        (23, 'training', 400, False),
        (0,  'training', 400, True),  # 00:00*
    ],

    # ── Воскресенье ──
    6: [
        (3,  'building', 900, False),
        (6,  'evolution', 800, False),
        (7,  'training+evolution+building', 400, False),
        (8,  'training', 400, False),
        (9,  'training', 400, False),
        (10, 'training+evolution+building', 400, False),
        (11, 'building', 900, False),
        (14, 'evolution', 800, False),
        (15, 'training+evolution+building', 400, False),
        (16, 'training', 400, False),
        (17, 'training', 400, False),
        (18, 'training+evolution+building', 400, False),
        (19, 'building', 900, False),
        (22, 'evolution', 800, False),
        (23, 'training+evolution+building', 400, False),
        (0,  'training', 400, True),  # 00:00*
        (1,  'training', 400, True),  # 01:00*
        (2,  'training+evolution+building', 400, True),  # 02:00*
    ],
}


# ═══════════════════════════════════════════════════
# КОМПИЛЯЦИЯ В ПЛОСКИЙ СЛОВАРЬ
# ═══════════════════════════════════════════════════
#
# {(физический_weekday, час): (тип, очки_за_мин)}
# Звёздочные события: физический_weekday = (игровой_day + 1) % 7

def _compile_schedule() -> Dict[tuple, tuple]:
    """
    Транслировать сырое расписание в плоский lookup.

    Returns:
        {(weekday, hour): (event_type, points_per_min)}
    """
    schedule = {}

    for game_day, events in _RAW_SCHEDULE.items():
        for hour, etype, ppm, is_next_day in events:
            if is_next_day:
                phys_day = (game_day + 1) % 7
            else:
                phys_day = game_day

            key = (phys_day, hour)

            if key in schedule:
                logger.warning(
                    f"⚠️ ds_schedule: дубликат ({DAY_NAMES[phys_day]} "
                    f"{hour:02d}:00), перезаписываем"
                )

            schedule[key] = (etype, ppm)

    return schedule


# Глобальный lookup (компилируется один раз при импорте)
_SCHEDULE: Dict[tuple, tuple] = _compile_schedule()


# ═══════════════════════════════════════════════════
# ДОПУСТИМЫЕ ТИПЫ УСКОРЕНИЙ
# ═══════════════════════════════════════════════════

_ALLOWED_SPEEDUP_TYPES = {
    'any': ['building', 'evolution', 'training', 'universal'],
    'building': ['building', 'universal'],
    'training': ['training'],
    'evolution': ['evolution'],
    'training+evolution+building': [
        'building', 'evolution', 'training', 'universal'
    ],
}


# ═══════════════════════════════════════════════════
# ПУБЛИЧНЫЙ API
# ═══════════════════════════════════════════════════

def get_current_event(now: datetime = None) -> Optional[Dict]:
    """
    Возвращает текущий активный ДС или None.

    ДС активен если:
    - (weekday, hour) есть в расписании
    - minute >= 5 (окно :05:00 — :59:59)

    Args:
        now: текущее время UTC+3 (по умолчанию datetime.now())

    Returns:
        {
            'type': 'building',
            'points_per_min': 900,
            'start': datetime,       # начало активного окна (:05:00)
            'end': datetime,         # конец активного окна (:59:59)
            'event_key': 'sun_03',   # уникальный ключ
        }
        или None если ДС неактивен
    """
    if now is None:
        now = datetime.now()

    # ДС активен только при minute >= 5
    if now.minute < DS_ACTIVE_START_MINUTE:
        return None

    key = (now.weekday(), now.hour)
    entry = _SCHEDULE.get(key)

    if entry is None:
        return None

    etype, ppm = entry

    return _build_event_dict(etype, ppm, now)


def get_next_event(now: datetime = None) -> Optional[Dict]:
    """
    Ближайший будущий ДС (для планировщика).

    Ищет вперёд по часам до 7 дней (168 часов).

    Args:
        now: текущее время UTC+3

    Returns:
        Словарь события (как в get_current_event) или None
    """
    if now is None:
        now = datetime.now()

    # Начинаем с ближайшего возможного часа
    if now.minute < DS_ACTIVE_START_MINUTE:
        # Текущий час ещё не начался — проверяем его
        candidate = now.replace(minute=0, second=0, microsecond=0)
    else:
        # Текущий час уже идёт — переходим к следующему
        candidate = now.replace(minute=0, second=0, microsecond=0)
        candidate += timedelta(hours=1)

    # Ищем до 168 часов вперёд (полная неделя)
    for _ in range(168):
        key = (candidate.weekday(), candidate.hour)
        entry = _SCHEDULE.get(key)

        if entry is not None:
            etype, ppm = entry
            start = candidate.replace(
                minute=DS_ACTIVE_START_MINUTE, second=0, microsecond=0
            )

            # Убедимся что start в будущем
            if start > now:
                return _build_event_dict(etype, ppm, candidate)

        candidate += timedelta(hours=1)

    return None


def is_safe_to_start(now: datetime = None, min_minutes: int = 5) -> bool:
    """
    Безопасно ли начинать выполнение ДС?

    Args:
        now: текущее время UTC+3
        min_minutes: минимум минут до конца ДС

    Returns:
        True если ДС активен И до конца >= min_minutes
        False иначе
    """
    event = get_current_event(now)
    if event is None:
        return False

    if now is None:
        now = datetime.now()

    remaining = (event['end'] - now).total_seconds()
    return remaining >= min_minutes * 60


def get_allowed_speedup_types(event_type: str) -> List[str]:
    """
    Какие типы ускорений можно тратить в данном типе ДС.

    Правила:
    - 'any'                         → building, evolution, training, universal
    - 'building'                    → building, universal
    - 'training'                    → training (universal НЕ напрямую)
    - 'evolution'                   → evolution (universal НИКОГДА)
    - 'training+evolution+building' → building, evolution, training, universal

    Args:
        event_type: тип события из расписания

    Returns:
        Список допустимых типов ускорений
    """
    result = _ALLOWED_SPEEDUP_TYPES.get(event_type)

    if result is None:
        logger.error(
            f"❌ ds_schedule: неизвестный тип события '{event_type}'"
        )
        return []

    return list(result)  # копия, чтобы вызывающий код не мог мутировать


def get_event_at(weekday: int, hour: int) -> Optional[Dict]:
    """
    Получить событие по конкретному дню и часу.

    Утилитарный метод для тестирования и отладки.

    Args:
        weekday: 0=Mon .. 6=Sun
        hour: 0-23

    Returns:
        {'type': ..., 'points_per_min': ...} или None
    """
    entry = _SCHEDULE.get((weekday, hour))
    if entry is None:
        return None

    etype, ppm = entry
    return {'type': etype, 'points_per_min': ppm}


def get_all_events_for_day(weekday: int) -> List[Dict]:
    """
    Все события конкретного дня (физического).

    Для отладки и GUI.

    Args:
        weekday: 0=Mon .. 6=Sun

    Returns:
        Список {'hour': int, 'type': str, 'points_per_min': int},
        отсортированный по часу.
    """
    events = []

    for (wd, hour), (etype, ppm) in _SCHEDULE.items():
        if wd == weekday:
            events.append({
                'hour': hour,
                'type': etype,
                'points_per_min': ppm,
                'event_key': f"{DAY_NAMES[wd]}_{hour:02d}",
            })

    events.sort(key=lambda e: e['hour'])
    return events


def get_total_events_count() -> int:
    """Общее количество событий в расписании (для тестов)."""
    return len(_SCHEDULE)


# ═══════════════════════════════════════════════════
# ВНУТРЕННИЕ УТИЛИТЫ
# ═══════════════════════════════════════════════════

def _build_event_dict(
    etype: str,
    ppm: int,
    ref_time: datetime
) -> Dict:
    """
    Сформировать словарь события.

    Args:
        etype: тип события
        ppm: очков за минуту
        ref_time: datetime с нужным днём и часом

    Returns:
        Полный словарь события
    """
    base = ref_time.replace(minute=0, second=0, microsecond=0)

    start = base.replace(minute=DS_ACTIVE_START_MINUTE)
    end = base.replace(minute=DS_ACTIVE_END_MINUTE, second=59)

    event_key = f"{DAY_NAMES[ref_time.weekday()]}_{ref_time.hour:02d}"

    return {
        'type': etype,
        'points_per_min': ppm,
        'start': start,
        'end': end,
        'event_key': event_key,
    }