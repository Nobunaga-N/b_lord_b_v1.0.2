"""
Калькулятор плана расхода ускорений для ДС

Чистая математика. Ноль зависимостей от ADB/OCR.
Зависимости: только ds_schedule (для get_allowed_speedup_types).

Ключевые правила:
  - Порог входа: ≥30ч ускорений 1m-3h нужного типа
  - Лимит: ≤65ч на один ДС
  - Приоритет номиналов: крупные → мелкие (3h→2h→1h→15m→10m→5m→1m)
  - Крупные (8h, 1d, 5d): можно если таймер впитает, в порог 30ч НЕ входят
  - Перерасход: до 4ч сверх target допустим (общий),
    до 10 мин на одну пачку (per-batch) если есть мелкие номиналы
  - Universal: building ✅, training ✅ (если нечего строить), evolution ❌
  - Алмазный финиш: остаток ≤22 мин, стоимость ≤70, нет мелких номиналов

ИЗМЕНЕНИЯ (v1.1 — bugfix):
  - Добавлена MAX_BATCH_OVERSPEND_SEC = 600 (10 мин)
  - Фаза 2: пропускает номинал если перерасход > 10 мин И есть мелкие номиналы
  - Добавлена _has_smaller_denoms() для проверки наличия мелких номиналов

API:
  calculate_plan(inventory, target_minutes, event_type, drain_type, ...)
    → SpeedupPlan

  choose_drain_type(inventory, event_type, has_buildings)
    → (drain_type, total_hours) или (None, 0)

  calculate_target_minutes(current_points, shell_points, points_per_min)
    → int

Версия: 1.1
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import logger


# ═══════════════════════════════════════════════════
# КОНСТАНТЫ
# ═══════════════════════════════════════════════════

# Номиналы в секундах
DENOM_SECONDS = {
    '1m': 60, '5m': 300, '10m': 600, '15m': 900,
    '1h': 3600, '2h': 7200, '3h': 10800, '8h': 28800,
    '1d': 86400, '5d': 432000,
}

# Порядок распределения: крупные → мелкие (основной диапазон)
DRAIN_ORDER = ['3h', '2h', '1h', '15m', '10m', '5m', '1m']

# Крупные номиналы (не входят в порог 30ч, используются осторожно)
LARGE_DENOMS = ['5d', '1d', '8h']

# Номиналы для подсчёта порога 30ч (1m — 3h)
THRESHOLD_DENOMS = {'1m', '5m', '10m', '15m', '1h', '2h', '3h'}

# Лимиты
THRESHOLD_HOURS = 30          # минимум часов для входа в ДС
MAX_TARGET_HOURS = 65         # максимум часов на один ДС
MAX_OVERSPEND_SEC = 4 * 3600  # допустимый перерасход общий (4 часа)

# ✅ FIX v1.1: Лимит перерасхода на одну пачку (10 мин)
# Если номинал создаёт перерасход > 10 мин И есть мелкие номиналы — пропускаем.
# Если мелких нет (крайний случай) — разрешаем крупный.
MAX_BATCH_OVERSPEND_SEC = 600  # 10 минут

# Алмазный финиш
DIAMOND_MAX_REMAINING_SEC = 22 * 60  # макс остаток для алмазов (22 мин)
DIAMOND_MAX_COST = 70                # макс стоимость в алмазах
DIAMOND_SMALL_DENOMS = {'1m', '5m'}  # номиналы которые могли бы заменить алмазы

# Максимум 1m ускорений за одну пачку (batch).
# 1m полезны для точного добивания — экономим, не тратим пачками.
#   1-3 шт → ок
#   4 шт нужно → предпочитаем 1×5m, если нет 5m → 4×1m допустимо
#   5+ шт нужно → алмазный финиш
MAX_1M_PER_BATCH = 3

# Правила universal для каждого drain_type
# True = universal разрешён, False = запрещён
UNIVERSAL_RULES = {
    'building': True,           # всегда
    'training': 'conditional',  # только если нечего строить
    'evolution': False,         # НИКОГДА
}


# ═══════════════════════════════════════════════════
# DATACLASSES
# ═══════════════════════════════════════════════════

@dataclass
class SpeedupPlanItem:
    """Одна позиция в плане расхода."""
    speedup_type: str       # 'building' / 'universal' / 'training' / 'evolution'
    denomination: str       # '1m' / '5m' / '1h' / ...
    quantity: int           # сколько штук потратить
    total_seconds: int      # суммарное время этих штук


@dataclass
class SpeedupPlan:
    """Полный план расхода ускорений."""
    drain_type: str                          # 'building' / 'training' / 'evolution'
    target_minutes: int                      # сколько нужно потратить всего
    target_shell: int                        # 1 или 2
    items: List[SpeedupPlanItem] = field(default_factory=list)
    use_diamonds: bool = False               # нужен ли алмазный финиш
    skip_reason: Optional[str] = None        # причина пропуска

    @property
    def total_seconds(self) -> int:
        """Суммарные секунды всех items."""
        return sum(item.total_seconds for item in self.items)

    @property
    def total_minutes(self) -> int:
        """Суммарные минуты (округлено вниз)."""
        return self.total_seconds // 60

    @property
    def is_skip(self) -> bool:
        """План = пропуск?"""
        return self.skip_reason is not None


# ═══════════════════════════════════════════════════
# ПУБЛИЧНЫЙ API
# ═══════════════════════════════════════════════════

def calculate_target_minutes(
    current_points: int,
    shell_points: int,
    points_per_min: int
) -> int:
    """
    Сколько минут ускорений нужно потратить для достижения ракушки.

    Формула: ceil((shell_points - current_points) / points_per_min)
    """
    if current_points >= shell_points:
        return 0

    diff = shell_points - current_points
    return math.ceil(diff / points_per_min)


def choose_drain_type(
    inventory: Dict[str, Dict[str, int]],
    event_type: str,
    has_buildings: bool = True,
    allowed_drain_types: Optional[List[str]] = None,
) -> Tuple[Optional[str], float]:
    """
    Выбрать лучший drain_type для комбинированного ДС.

    Алгоритм:
    1. Для каждого допустимого типа подсчитать часы (1m-3h)
       + universal если разрешён
    2. Отфильтровать типы с < 30ч
    3. Выбрать тип с наибольшим запасом
    """
    from functions.prime_times.ds_schedule import get_allowed_speedup_types

    allowed = get_allowed_speedup_types(event_type)
    if not allowed:
        return None, 0

    universal_hours = _calc_threshold_hours(
        inventory.get('universal', {})
    )

    candidates = []

    possible_drains = set()
    for stype in allowed:
        if stype == 'universal':
            continue
        possible_drains.add(stype)

    # ── ФИЛЬТР ПО GUI-НАСТРОЙКАМ ──
    if allowed_drain_types is not None:
        before = possible_drains.copy()
        possible_drains &= set(allowed_drain_types)
        filtered = before - possible_drains
        if filtered:
            logger.debug(
                f"🔧 choose_drain_type: отфильтрованы типы "
                f"по GUI: {filtered}"
            )

    if not possible_drains:
        return None, 0

    for dtype in possible_drains:
        type_hours = _calc_threshold_hours(
            inventory.get(dtype, {})
        )

        total = type_hours
        uni_rule = UNIVERSAL_RULES.get(dtype, False)

        if uni_rule is True:
            total += universal_hours
        elif uni_rule == 'conditional' and not has_buildings:
            total += universal_hours

        if total >= THRESHOLD_HOURS:
            candidates.append((dtype, total))

    if not candidates:
        return None, 0

    candidates.sort(key=lambda x: x[1], reverse=True)
    best_type, best_hours = candidates[0]

    logger.debug(
        f"📊 choose_drain_type: {event_type} → {best_type} "
        f"({best_hours:.1f}ч), кандидаты: "
        f"{[(t, f'{h:.1f}ч') for t, h in candidates]}"
    )

    return best_type, best_hours


def calculate_plan(
    inventory: Dict[str, Dict[str, int]],
    target_minutes: int,
    event_type: str,
    drain_type: str,
    has_buildings: bool = True,
    target_shell: int = 2,
    timers: Optional[Dict[str, int]] = None,
    skip_threshold: bool = False,
) -> SpeedupPlan:
    """
    Рассчитать оптимальный план расхода ускорений.

    Три фазы распределения:
      Фаза 1: крупные номиналы (8h, 1d, 5d) — если таймер впитает
      Фаза 2: основной диапазон (3h → 5m) — жадный floor-алгоритм
      Фаза 3: добивание остатка (1m ≤ 3шт, 5m fallback, алмазы)

    Args:
        inventory: {speedup_type: {denomination: quantity}} из БД
        target_minutes: сколько минут ускорений нужно потратить
        event_type: тип ДС (для определения допустимых типов)
        drain_type: выбранный тип ('building' / 'training' / 'evolution')
        has_buildings: есть ли здания для улучшения
        target_shell: целевая ракушка (1 или 2)
        timers: {slot_name: seconds} — текущие таймеры
        skip_threshold: True при расчёте плана на одну пачку

    Returns:
        SpeedupPlan с заполненными items
    """
    plan = SpeedupPlan(
        drain_type=drain_type,
        target_minutes=target_minutes,
        target_shell=target_shell,
    )

    # ── Проверка лимита 65ч ──
    if target_minutes > MAX_TARGET_HOURS * 60:
        plan.skip_reason = '>65h'
        logger.info(
            f"⏭️ ДС пропущен: target={target_minutes} мин "
            f"(>{MAX_TARGET_HOURS}ч, невыгодно)"
        )
        return plan

    # ── Собираем доступные ускорения ──
    # Типовые первыми, universal вторыми (приоритет по порядку вставки)
    available = _collect_available(
        inventory, drain_type, has_buildings
    )

    if not available:
        plan.skip_reason = 'not_enough_speedups'
        return plan

    # ── Проверяем порог 30ч (только при первичном расчёте) ──
    if not skip_threshold:
        threshold_sec = _calc_threshold_seconds_from_available(available)
        threshold_hours = threshold_sec / 3600

        if threshold_hours < THRESHOLD_HOURS:
            plan.skip_reason = 'not_enough_speedups'
            logger.info(
                f"⏭️ ДС пропущен: {drain_type} = "
                f"{threshold_hours:.1f}ч "
                f"(< {THRESHOLD_HOURS}ч порог)"
            )
            return plan

    # ── Распределяем номиналы ──
    target_sec = target_minutes * 60
    remaining_sec = target_sec
    max_total_sec = target_sec + MAX_OVERSPEND_SEC

    # Макс таймер для ограничения крупных номиналов
    max_timer = _get_max_timer(timers, drain_type) if timers else None

    # ═══════════════════════════════════════════════════════
    # Фаза 1: крупные номиналы (8h, 1d, 5d)
    # Используются ТОЛЬКО если таймер здания/тренировки/эволюции
    # достаточно большой для "впитывания" без критического перерасхода.
    # В порог 30ч НЕ входят.
    # ═══════════════════════════════════════════════════════
    if max_timer is not None and max_timer > 0:
        for denom in LARGE_DENOMS:
            if remaining_sec <= 0:
                break

            denom_sec = DENOM_SECONDS[denom]

            # Крупный номинал — только если таймер достаточно большой
            if denom_sec > max_timer:
                continue

            for stype, sdenoms in available.items():
                if remaining_sec <= 0:
                    break

                qty = sdenoms.get(denom, 0)
                if qty <= 0:
                    continue

                max_by_remaining = max(1, remaining_sec // denom_sec)
                max_by_limit = max(
                    0,
                    (max_total_sec - (target_sec - remaining_sec))
                    // denom_sec
                )
                use_qty = min(qty, max_by_remaining, max_by_limit)

                if use_qty <= 0:
                    continue

                item_sec = use_qty * denom_sec
                plan.items.append(SpeedupPlanItem(
                    speedup_type=stype,
                    denomination=denom,
                    quantity=use_qty,
                    total_seconds=item_sec,
                ))
                remaining_sec -= item_sec
                sdenoms[denom] -= use_qty

    # ═══════════════════════════════════════════════════════
    # Фаза 2: основной диапазон (3h → 5m), БЕЗ 1m
    #
    # ✅ FIX v1.2: floor вместо ceil для жадного алгоритма.
    #    ceil давал перерасход (23м → 2×15m = 30м).
    #    floor даёт точное покрытие (23м → 15m + 5m + 3×1m).
    #    1m обрабатывается отдельно в Фазе 3 (лимит 3 шт).
    # ═══════════════════════════════════════════════════════
    DRAIN_ORDER_NO_1M = ['3h', '2h', '1h', '15m', '10m', '5m']

    for denom in DRAIN_ORDER_NO_1M:
        if remaining_sec <= 0:
            break

        denom_sec = DENOM_SECONDS[denom]

        # Пропускаем если перерасход > 10 мин и есть мелкие номиналы
        if denom_sec > remaining_sec + MAX_BATCH_OVERSPEND_SEC:
            if _has_smaller_denoms(available, denom):
                logger.debug(
                    f"⏭️ Пропуск {denom}: {denom_sec}с > "
                    f"remaining {remaining_sec}с + лимит "
                    f"{MAX_BATCH_OVERSPEND_SEC}с, есть мелкие"
                )
                continue

        for stype, sdenoms in available.items():
            if remaining_sec <= 0:
                break

            qty = sdenoms.get(denom, 0)
            if qty <= 0:
                continue

            # ✅ floor — макс целых номиналов без перерасхода
            use_qty = min(qty, remaining_sec // denom_sec)

            # Общий перерасход (лимит 4ч)
            spent_so_far = target_sec - remaining_sec
            would_spend = spent_so_far + use_qty * denom_sec
            if would_spend > max_total_sec and use_qty > 1:
                use_qty = max(
                    0,
                    (max_total_sec - spent_so_far) // denom_sec
                )

            if use_qty <= 0:
                continue

            item_sec = use_qty * denom_sec
            plan.items.append(SpeedupPlanItem(
                speedup_type=stype,
                denomination=denom,
                quantity=use_qty,
                total_seconds=item_sec,
            ))
            remaining_sec -= item_sec
            sdenoms[denom] -= use_qty

    # ═══════════════════════════════════════════════════════
    # Фаза 3: добивание остатка (1m + 5m fallback + алмазы)
    #
    # Правила для 1m (экономим — ценны для точного добивания):
    #   1-3 шт → ок
    #   4 шт нужно → предпочитаем 1×5m, если нет 5m → 4×1m
    #   5+ шт нужно → комбинация 5m + 1m, иначе алмазы
    # ═══════════════════════════════════════════════════════
    if remaining_sec > 0:
        # Считаем доступные 1m и 5m по всем типам
        avail_1m = sum(
            sdenoms.get('1m', 0)
            for sdenoms in available.values()
        )
        avail_5m = sum(
            sdenoms.get('5m', 0)
            for sdenoms in available.values()
        )

        needed_1m = math.ceil(remaining_sec / 60)

        logger.debug(
            f"🔧 Фаза 3: remaining={remaining_sec}с "
            f"(~{needed_1m}×1m), avail_1m={avail_1m}, "
            f"avail_5m={avail_5m}"
        )

        if needed_1m <= MAX_1M_PER_BATCH:
            # ─── Случай A: 1-3×1m → просто используем ───
            use_1m = min(needed_1m, avail_1m)
            if use_1m > 0:
                _add_1m_to_plan(plan, available, use_1m)
                remaining_sec -= use_1m * 60

            # Если 1m не хватило → алмазы на остаток
            if remaining_sec > 0 \
                    and remaining_sec <= DIAMOND_MAX_REMAINING_SEC:
                plan.use_diamonds = True
                logger.debug(
                    f"💎 Фаза 3: алмазы на остаток "
                    f"{remaining_sec}с (мало 1m)"
                )

        elif needed_1m == MAX_1M_PER_BATCH + 1:
            # ─── Случай B: 4×1m → предпочитаем 1×5m ───
            if avail_5m > 0:
                _add_denom_to_plan(plan, available, '5m', 1)
                remaining_sec -= 300
                logger.debug(
                    f"✅ Фаза 3: 1×5m вместо 4×1m "
                    f"(remaining={remaining_sec}с)"
                )
            elif avail_1m >= 4:
                # Нет 5m → допускаем 4×1m
                _add_1m_to_plan(plan, available, 4)
                remaining_sec -= 4 * 60
                logger.debug("✅ Фаза 3: 4×1m (нет 5m)")
            else:
                # Мало и 5m и 1m → сколько есть + алмазы
                use_1m = min(MAX_1M_PER_BATCH, avail_1m)
                if use_1m > 0:
                    _add_1m_to_plan(plan, available, use_1m)
                    remaining_sec -= use_1m * 60
                if remaining_sec > 0 \
                        and remaining_sec <= DIAMOND_MAX_REMAINING_SEC:
                    plan.use_diamonds = True

        else:
            # ─── Случай C: 5+×1m → 5m + 1m или алмазы ───
            if avail_5m > 0:
                # Покрываем основную часть через 5m
                use_5m = min(avail_5m, remaining_sec // 300)
                if use_5m > 0:
                    _add_denom_to_plan(plan, available, '5m', use_5m)
                    remaining_sec -= use_5m * 300

                # Хвост — 1m (до 3 штук)
                if remaining_sec > 0:
                    tail_1m = min(
                        math.ceil(remaining_sec / 60),
                        MAX_1M_PER_BATCH,
                        avail_1m,
                    )
                    if tail_1m > 0:
                        _add_1m_to_plan(plan, available, tail_1m)
                        remaining_sec -= tail_1m * 60

                # Всё ещё остаток → алмазы
                if remaining_sec > 0 \
                        and remaining_sec <= DIAMOND_MAX_REMAINING_SEC:
                    plan.use_diamonds = True
            else:
                # Нет 5m → до 3×1m + алмазы
                use_1m = min(MAX_1M_PER_BATCH, avail_1m)
                if use_1m > 0:
                    _add_1m_to_plan(plan, available, use_1m)
                    remaining_sec -= use_1m * 60
                if remaining_sec > 0 \
                        and remaining_sec <= DIAMOND_MAX_REMAINING_SEC:
                    plan.use_diamonds = True
                    logger.debug(
                        f"💎 Фаза 3: алмазы на остаток "
                        f"{remaining_sec}с (нет 5m, 1m ограничены)"
                    )

    # ── Финальная страховка: алмазный финиш ──
    if remaining_sec > 0 and not plan.use_diamonds:
        has_small = _has_small_denoms(available)
        if not has_small \
                and remaining_sec <= DIAMOND_MAX_REMAINING_SEC:
            plan.use_diamonds = True
            logger.debug(
                f"💎 Алмазный финиш: остаток "
                f"{remaining_sec // 60} мин"
            )

    _log_plan(plan, remaining_sec)
    return plan


def estimate_diamond_cost(remaining_seconds: int) -> int:
    """
    Примерная оценка стоимости алмазного финиша.
    В среднем ~1 алмаз за ~20 секунд ускорения.
    """
    if remaining_seconds <= 0:
        return 0
    return max(1, math.ceil(remaining_seconds / 20))


# ═══════════════════════════════════════════════════
# ВНУТРЕННИЕ УТИЛИТЫ
# ═══════════════════════════════════════════════════

def _calc_threshold_hours(
    denoms: Dict[str, int]
) -> float:
    """
    Подсчитать часы для порога 30ч.
    Учитываются ТОЛЬКО номиналы 1m-3h.
    """
    total_sec = 0
    for denom, qty in denoms.items():
        if denom in THRESHOLD_DENOMS and qty > 0:
            total_sec += DENOM_SECONDS.get(denom, 0) * qty
    return total_sec / 3600


def _calc_threshold_seconds_from_available(
    available: Dict[str, Dict[str, int]]
) -> int:
    """
    Подсчитать суммарные секунды порогового диапазона (1m-3h)
    из собранного available dict.
    """
    total = 0
    for stype, denoms in available.items():
        for denom, qty in denoms.items():
            if denom in THRESHOLD_DENOMS and qty > 0:
                total += DENOM_SECONDS.get(denom, 0) * qty
    return total


def _collect_available(
    inventory: Dict[str, Dict[str, int]],
    drain_type: str,
    has_buildings: bool
) -> Dict[str, Dict[str, int]]:
    """
    Собрать доступные ускорения для drain_type.
    Возвращает КОПИЮ (мутировать безопасно).

    ВАЖНО: порядок вставки = приоритет траты.
    Типовые ускорения (building/training/evolution) вставляются ПЕРВЫМИ,
    universal — ВТОРЫМИ. При итерации `for stype in available` типовые
    обрабатываются раньше, что обеспечивает:
      building/15m тратится ДО universal/15m.

    Python 3.7+ гарантирует сохранение порядка вставки в dict.
    """
    result = {}

    # ── 1. Типовые ПЕРВЫМИ (приоритет) ──
    main_denoms = inventory.get(drain_type, {})
    if main_denoms:
        result[drain_type] = dict(main_denoms)

    # ── 2. Universal ВТОРЫМИ ──
    uni_rule = UNIVERSAL_RULES.get(drain_type, False)
    add_universal = False

    if uni_rule is True:
        add_universal = True
    elif uni_rule == 'conditional' and not has_buildings:
        add_universal = True

    if add_universal:
        uni_denoms = inventory.get('universal', {})
        if uni_denoms:
            result['universal'] = dict(uni_denoms)

    return result


def _get_max_timer(
    timers: Dict[str, int],
    drain_type: str
) -> Optional[int]:
    """
    Получить максимальный таймер для drain_type.
    """
    if not timers:
        return None

    relevant = []

    if drain_type == 'building':
        for key, val in timers.items():
            if key.startswith('building') and val > 0:
                relevant.append(val)

    elif drain_type == 'training':
        for key, val in timers.items():
            if key.startswith('training') and val > 0:
                relevant.append(val)

    elif drain_type == 'evolution':
        val = timers.get('evolution', 0)
        if val > 0:
            relevant.append(val)

    return max(relevant) if relevant else None


def _has_small_denoms(
    available: Dict[str, Dict[str, int]]
) -> bool:
    """Есть ли мелкие номиналы (1m, 5m) для добивания?"""
    for stype, denoms in available.items():
        for denom in DIAMOND_SMALL_DENOMS:
            if denoms.get(denom, 0) > 0:
                return True
    return False


def _has_smaller_denoms(
    available: Dict[str, Dict[str, int]],
    current_denom: str,
) -> bool:
    """
    ✅ FIX v1.1: Есть ли номиналы МЕЛЬЧЕ current_denom в available?
    Используется для решения: пропустить крупный номинал или нет.
    """
    current_sec = DENOM_SECONDS[current_denom]
    for stype, denoms in available.items():
        for d, qty in denoms.items():
            if qty > 0 and DENOM_SECONDS.get(d, 0) < current_sec:
                return True
    return False


def _add_1m_to_plan(
    plan,  # SpeedupPlan
    available: Dict[str, Dict[str, int]],
    count: int,
):
    """
    Добавить до `count` штук 1m в план.

    Итерирует available.items() → типовые 1m первыми,
    universal 1m вторыми (приоритет по порядку вставки).
    """
    left = count
    for stype, sdenoms in available.items():
        if left <= 0:
            break
        qty = sdenoms.get('1m', 0)
        if qty <= 0:
            continue

        use = min(qty, left)
        item_sec = use * 60
        plan.items.append(SpeedupPlanItem(
            speedup_type=stype,
            denomination='1m',
            quantity=use,
            total_seconds=item_sec,
        ))
        sdenoms['1m'] -= use
        left -= use


def _add_denom_to_plan(
    plan,  # SpeedupPlan
    available: Dict[str, Dict[str, int]],
    denom: str,
    count: int,
):
    """
    Добавить до `count` штук указанного номинала в план.

    Итерирует available.items() → типовые первыми,
    universal вторыми.
    """
    denom_sec = DENOM_SECONDS[denom]
    left = count
    for stype, sdenoms in available.items():
        if left <= 0:
            break
        qty = sdenoms.get(denom, 0)
        if qty <= 0:
            continue

        use = min(qty, left)
        item_sec = use * denom_sec
        plan.items.append(SpeedupPlanItem(
            speedup_type=stype,
            denomination=denom,
            quantity=use,
            total_seconds=item_sec,
        ))
        sdenoms[denom] -= use
        left -= use

def _log_plan(plan: SpeedupPlan, remaining_sec: int):
    """Логирование плана."""
    if plan.is_skip:
        return

    parts = []
    for item in plan.items:
        parts.append(
            f"{item.speedup_type}/{item.denomination}×{item.quantity}"
        )

    total_min = plan.total_minutes
    items_str = ', '.join(parts) if parts else 'пусто'

    msg = (
        f"📋 План ДС: drain={plan.drain_type}, "
        f"target={plan.target_minutes} мин, "
        f"planned={total_min} мин, "
        f"items=[{items_str}]"
    )

    if remaining_sec > 0:
        msg += f", остаток={remaining_sec // 60} мин"
    if plan.use_diamonds:
        msg += ", 💎 алмазный финиш"

    logger.info(msg)