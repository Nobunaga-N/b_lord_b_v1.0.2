"""
Применение ускорений в игровом окне (UI-модуль)

Получает SpeedupPlan от калькулятора и физически тратит ускорения
через ADB + OCR. Работает в трёх контекстах:
  - building:  бот уже в окне ускорений (после клика "Ускорить")
  - training:  бот в окне ускорений (после клика "Ускорение" из тренировки)
  - evolution: бот в окне ускорений (после клика "Ускорение" из эволюции)

Предусловие: окно ускорений УЖЕ ОТКРЫТО.

Алгоритм:
  1. Для каждого item из плана → найти номинал на экране через OCR
  2. Кликать "Использовать" нужное кол-во раз
  3. После каждого клика: обновить БД, проверить завершение
  4. При закончившемся номинале: пересканировать позиции
  5. Свайпы вниз/назад при необходимости
  6. Алмазный финиш в крайнем случае

Контексты завершения:
  - building:  панель навигации (navigation_icon) = окно закрылось
  - training:  кнопка "Обучение" (button_training) = вернулись к тренировке
  - evolution: крестик (evolution_close_x) = закрылись 2 окна

Версия: 1.0
"""

import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger

from functions.backpack_speedups.backpack_storage import (
    BackpackStorage, DENOM_SECONDS
)
from functions.prime_times.prime_storage import PrimeStorage


# ═══════════════════════════════════════════════════
# ПУТИ К ШАБЛОНАМ
# ═══════════════════════════════════════════════════

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

TEMPLATES = {
    'button_confirm': os.path.join(
        BASE_DIR, 'data', 'templates', 'prime_times', 'button_confirm.png'
    ),
    'button_training': os.path.join(
        BASE_DIR, 'data', 'templates', 'prime_times', 'button_training.png'
    ),
    'evolution_close_x': os.path.join(
        BASE_DIR, 'data', 'templates', 'prime_times', 'evolution_close_x.png'
    ),
    'navigation_icon': os.path.join(
        BASE_DIR, 'data', 'templates', 'building', 'navigation_icon.png'
    ),
}


# ═══════════════════════════════════════════════════
# КООРДИНАТЫ (540×960, 240 DPI)
# ═══════════════════════════════════════════════════

COORD_USE_BUTTON_X = 466        # X кнопки "Использовать"
COORD_DIAMOND_BUTTON = (475, 248)  # Кнопка "Завершить Сейчас" (стартовая позиция)
AREA_DIAMONDS = (414, 30, 488, 51)  # OCR область текущих алмазов

# Область таймера в окне ускорений
TIMER_AREAS = {
    'building': (213, 67, 335, 106),
    'training': (213, 67, 335, 106),
    'evolution': (214, 74, 317, 104),
}

# Свайпы (duration=800 — плавные, без инерции)
SWIPE_DOWN = {
    'x1': 230, 'y1': 812, 'x2': 230, 'y2': 172, 'duration': 800
}
SWIPE_BACK = {
    'x1': 230, 'y1': 211, 'x2': 230, 'y2': 910, 'duration': 800
}

# Видимая область строк ускорений
SPEEDUP_ROWS_Y_MIN = 195
SPEEDUP_ROWS_Y_MAX = 936

# ═══════════════════════════════════════════════════
# ПОРОГИ И ТАЙМИНГИ
# ═══════════════════════════════════════════════════

THRESHOLD_TEMPLATE = 0.80
MAX_SWIPES_DOWN = 2

DELAY_AFTER_USE = 0.8       # после клика "Использовать"
DELAY_AFTER_LAST_USE = 1.5  # после клика который может завершить улучшение
DELAY_AFTER_SWIPE = 1.0
DELAY_AFTER_CONFIRM = 2.0
DELAY_AFTER_RESCAN = 0.5

# Алмазный финиш
DIAMOND_MAX_REMAINING_SEC = 22 * 60  # 22 мин
DIAMOND_MAX_COST = 70


# ═══════════════════════════════════════════════════
# МАППИНГ: OCR-текст → (speedup_type, denomination)
# ═══════════════════════════════════════════════════

# Ключевые слова в названии ускорения для определения типа
_TYPE_KEYWORDS = {
    'Строительства': 'building',
    'строительства': 'building',
    'Обучения':      'training',
    'обучения':      'training',
    'Эволюции':      'evolution',
    'эволюции':      'evolution',
}

# Паттерн номинала в скобках: "(5 мин.)" / "(1 ч.)" / "(5 дн.)"
_DENOM_PATTERN = re.compile(
    r'\((\d+)\s*(мин|ч|дн)\.?\)', re.IGNORECASE
)

# Конвертация единицы из OCR → суффикс denomination
_UNIT_MAP = {
    'мин': 'm',
    'ч':   'h',
    'дн':  'd',
}


# ═══════════════════════════════════════════════════
# DATACLASSES
# ═══════════════════════════════════════════════════

@dataclass
class SpeedupSlot:
    """Одна видимая строка ускорения на экране."""
    speedup_type: str       # 'building' / 'training' / 'evolution' / 'universal'
    denomination: str       # '1m', '5m', '1h', ...
    button_x: int           # X координата кнопки "Использовать"
    button_y: int           # Y координата кнопки "Использовать"


@dataclass
class DrainResult:
    """Результат траты ускорений."""
    minutes_spent: float = 0.0          # суммарные минуты потраченных ускорений
    speedups_used: Dict[str, int] = field(default_factory=dict)
    building_completed: bool = False    # улучшение завершилось?
    remaining_timer: Optional[int] = None  # оставшийся таймер (сек)
    diamonds_used: int = 0
    error: Optional[str] = None


# ═══════════════════════════════════════════════════
# ПУБЛИЧНЫЙ API
# ═══════════════════════════════════════════════════

def drain_speedups(
    emulator: Dict,
    plan,  # SpeedupPlan из speedup_calculator
    context: str,
    session_state: Dict,
) -> DrainResult:
    """
    Потратить ускорения в текущем окне ускорений.

    Предусловие: окно ускорений ОТКРЫТО. Бот видит список
    номиналов и кнопки "Использовать".

    Args:
        emulator: dict эмулятора (id, name, port)
        plan: SpeedupPlan с заполненными items
        context: 'building' / 'training' / 'evolution'
        session_state: текущий session_state

    Returns:
        DrainResult с информацией о потраченных ускорениях
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
    emu_id = emulator.get('id')

    result = DrainResult()
    ocr = OCREngine(lang='ru')
    storage = BackpackStorage()

    if not plan or not plan.items:
        logger.warning(f"[{emu_name}] ⚠️ Пустой план ускорений")
        return result

    logger.info(
        f"[{emu_name}] 🚀 Начинаем drain: context={context}, "
        f"items={len(plan.items)}, target={plan.target_minutes} мин"
    )

    # Текущая позиция свайпа (0 = стартовая, 1-2 = свайпнули вниз)
    swipe_position = 0

    for item_idx, item in enumerate(plan.items):
        remaining_qty = item.quantity

        logger.info(
            f"[{emu_name}] 📦 Item {item_idx + 1}/{len(plan.items)}: "
            f"{item.speedup_type}/{item.denomination} × {item.quantity}"
        )

        while remaining_qty > 0:
            # ── 1. Сканируем видимые ускорения ──
            slots = _scan_visible_speedups(emulator, ocr)

            # ── 2. Ищем нужный номинал ──
            target_slot = _find_target_slot(
                slots, item.speedup_type, item.denomination
            )

            if target_slot is None:
                # Не видно → пытаемся найти свайпами
                target_slot = _find_with_swipes(
                    emulator, ocr, item.speedup_type,
                    item.denomination, swipe_position
                )

                if target_slot is not None:
                    # Обновляем позицию свайпа
                    # (find_with_swipes мог свайпнуть)
                    swipe_position = -1  # неизвестная позиция

                if target_slot is None:
                    logger.warning(
                        f"[{emu_name}] ⚠️ Номинал "
                        f"{item.speedup_type}/{item.denomination} "
                        f"не найден на экране, пропускаем"
                    )
                    break

            # ── 3. Кликаем "Использовать" × remaining_qty ──
            used, completed = _apply_clicks(
                emulator, ocr, target_slot, remaining_qty,
                item.speedup_type, item.denomination,
                storage, emu_id, context, result
            )

            remaining_qty -= used

            # Обновляем result
            key = f"{item.speedup_type}/{item.denomination}"
            result.speedups_used[key] = (
                result.speedups_used.get(key, 0) + used
            )
            denom_sec = DENOM_SECONDS.get(item.denomination, 0)
            result.minutes_spent += used * (denom_sec / 60)

            if completed:
                result.building_completed = True
                logger.success(
                    f"[{emu_name}] 🎉 Улучшение завершилось! "
                    f"Потрачено {result.minutes_spent:.0f} мин"
                )
                return result

            # После apply_clicks позиция свайпа неопределена
            # (номинал мог закончиться и строки сдвинулись)
            swipe_position = -1

    # ── Алмазный финиш (если нужен) ──
    if plan.use_diamonds and not result.building_completed:
        diamond_ok = _try_diamond_finish(emulator, ocr, context, result)
        if diamond_ok:
            result.building_completed = True
            logger.success(
                f"[{emu_name}] 💎 Алмазный финиш! "
                f"Потрачено {result.minutes_spent:.0f} мин"
            )
            return result

    # ── Парсинг оставшегося таймера ──
    if not result.building_completed:
        result.remaining_timer = _parse_remaining_timer(
            emulator, ocr, context
        )

    logger.info(
        f"[{emu_name}] ✅ Drain завершён: "
        f"{result.minutes_spent:.0f} мин потрачено, "
        f"completed={result.building_completed}, "
        f"remaining={result.remaining_timer}"
    )

    return result


# ═══════════════════════════════════════════════════
# СКАНИРОВАНИЕ ЭКРАНА (OCR)
# ═══════════════════════════════════════════════════

def _scan_visible_speedups(
    emulator: Dict,
    ocr: OCREngine
) -> List[SpeedupSlot]:
    """
    OCR-сканирование видимых ускорений на экране.

    Алгоритм:
    1. Скриншот → OCR всего экрана
    2. Группировка элементов по близости Y (±25px)
    3. Для каждой группы: склеить текст → парсить тип + номинал
    4. Результат: список SpeedupSlot отсортированный по Y

    Returns:
        List[SpeedupSlot]: видимые ускорения с координатами кнопок
    """
    screenshot = get_screenshot(emulator)
    if screenshot is None:
        return []

    elements = ocr.recognize_text(screenshot, min_confidence=0.3)
    if not elements:
        return []

    # Группируем элементы по Y (строки)
    groups = _group_by_y(elements, threshold=25)

    slots = []
    for group in groups:
        # Склеиваем тексты группы
        combined = ' '.join(e['text'] for e in group)

        # Парсим тип + номинал
        parsed = _parse_speedup_text(combined)
        if parsed is None:
            continue

        stype, denom = parsed

        # Y = средняя Y координата группы
        avg_y = int(sum(e['y'] for e in group) / len(group))

        # Фильтруем по видимой области
        if avg_y < SPEEDUP_ROWS_Y_MIN or avg_y > SPEEDUP_ROWS_Y_MAX:
            continue

        slots.append(SpeedupSlot(
            speedup_type=stype,
            denomination=denom,
            button_x=COORD_USE_BUTTON_X,
            button_y=avg_y + 27,  # кнопка "Использовать" на 27px ниже текста
        ))

    # Сортировка по Y (сверху вниз)
    slots.sort(key=lambda s: s.button_y)

    if slots:
        labels = [f"{s.speedup_type}/{s.denomination}(y={s.button_y})"
                  for s in slots]
        logger.debug(f"  Видимые ускорения: [{', '.join(labels)}]")

    return slots


def _group_by_y(
    elements: List[Dict],
    threshold: int = 25
) -> List[List[Dict]]:
    """
    Группировка OCR-элементов по близости Y.

    Элементы с |y1 - y2| <= threshold попадают в одну группу.
    Внутри группы сортируются по X (слева направо).

    Returns:
        Список групп, каждая группа — список элементов
    """
    if not elements:
        return []

    # Сортируем по Y
    sorted_els = sorted(elements, key=lambda e: e['y'])

    groups = []
    current_group = [sorted_els[0]]
    current_y = sorted_els[0]['y']

    for el in sorted_els[1:]:
        if abs(el['y'] - current_y) <= threshold:
            current_group.append(el)
        else:
            groups.append(sorted(current_group, key=lambda e: e['x']))
            current_group = [el]
            current_y = el['y']

    if current_group:
        groups.append(sorted(current_group, key=lambda e: e['x']))

    return groups


def _parse_speedup_text(text: str) -> Optional[Tuple[str, str]]:
    """
    Парсинг текста строки ускорения → (speedup_type, denomination).

    Примеры:
        "Ускорение Строительства (1 ч.)"  → ('building', '1h')
        "Ускорение Обучения Зверей (5 мин.)" → ('training', '5m')
        "Ускорение Эволюции (15 мин.)"    → ('evolution', '15m')
        "Ускорение (1 мин.)"              → ('universal', '1m')
        "Ускорение (5 дн.)"               → ('universal', '5d')

    Returns:
        (speedup_type, denomination) или None
    """
    # Проверяем наличие "Ускорение" (или "ускорение")
    text_lower = text.lower()
    if 'ускорение' not in text_lower and 'ускорени' not in text_lower:
        return None

    # Пропускаем "Завершить Сейчас"
    if 'завершить' in text_lower or 'автоускорение' in text_lower:
        return None

    # Определяем тип
    stype = 'universal'
    for keyword, type_name in _TYPE_KEYWORDS.items():
        if keyword in text:
            stype = type_name
            break

    # Извлекаем номинал из скобок
    match = _DENOM_PATTERN.search(text)
    if not match:
        return None

    value = match.group(1)  # "5", "1", "15"
    unit = match.group(2).lower()  # "мин", "ч", "дн"

    suffix = _UNIT_MAP.get(unit)
    if suffix is None:
        return None

    denomination = f"{value}{suffix}"

    # Валидация
    if denomination not in DENOM_SECONDS:
        logger.debug(
            f"  _parse_speedup_text: неизвестный номинал "
            f"'{denomination}' из '{text}'"
        )
        return None

    return stype, denomination


# ═══════════════════════════════════════════════════
# ПОИСК НОМИНАЛА НА ЭКРАНЕ
# ═══════════════════════════════════════════════════

def _find_target_slot(
    slots: List[SpeedupSlot],
    speedup_type: str,
    denomination: str
) -> Optional[SpeedupSlot]:
    """Найти нужный номинал среди видимых слотов."""
    for slot in slots:
        if slot.speedup_type == speedup_type and slot.denomination == denomination:
            return slot
    return None


def _find_with_swipes(
    emulator: Dict,
    ocr: OCREngine,
    speedup_type: str,
    denomination: str,
    current_swipe_pos: int,
) -> Optional[SpeedupSlot]:
    """
    Поиск номинала с помощью свайпов.

    Стратегия:
    1. Сначала пробуем свайпы вниз (макс 2)
    2. Если не нашли → возврат к началу (2 свайпа назад) → пересканирование

    Returns:
        SpeedupSlot или None
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    # Свайпы вниз
    for i in range(MAX_SWIPES_DOWN):
        logger.debug(f"[{emu_name}] ⬇️ Свайп вниз {i + 1}/{MAX_SWIPES_DOWN}")
        _do_swipe_down(emulator)

        slots = _scan_visible_speedups(emulator, ocr)
        target = _find_target_slot(slots, speedup_type, denomination)
        if target is not None:
            return target

    # Не нашли → возврат к началу
    logger.debug(f"[{emu_name}] ⬆️ Возврат к стартовой позиции")
    _do_swipe_to_start(emulator)

    slots = _scan_visible_speedups(emulator, ocr)
    target = _find_target_slot(slots, speedup_type, denomination)
    return target


# ═══════════════════════════════════════════════════
# ПРИМЕНЕНИЕ КЛИКОВ
# ═══════════════════════════════════════════════════

def _apply_clicks(
    emulator: Dict,
    ocr: OCREngine,
    slot: SpeedupSlot,
    max_clicks: int,
    speedup_type: str,
    denomination: str,
    storage: BackpackStorage,
    emu_id: int,
    context: str,
    result: DrainResult,
) -> Tuple[int, bool]:
    """
    Кликать "Использовать" до max_clicks раз.

    После каждого клика:
    - Обновляет БД (use_speedup)
    - Проверяет: закончился ли номинал (quantity=0 → выход, нужен rescan)
    - Проверяет: завершилось ли улучшение (confirm / контекстный маркер)

    ВАЖНО: проверка завершения выполняется ПОСЛЕ КАЖДОГО клика.
    Даже с per-batch планированием, таймер мог уменьшиться
    между парсингом и drain (навигация, задержки). Без проверки
    бот продолжает кликать в пустоту после закрытия окна.

    Returns:
        (used_count, completed): сколько использовали, завершилось ли
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    used = 0
    denom_sec = DENOM_SECONDS.get(denomination, 0)

    db_qty = storage.get_quantity(emu_id, speedup_type, denomination)

    for i in range(max_clicks):
        if db_qty <= 0:
            logger.debug(
                f"[{emu_name}] Номинал {speedup_type}/{denomination} "
                f"закончился в БД"
            )
            break

        # Клик "Использовать"
        tap(emulator, slot.button_x, slot.button_y)
        used += 1

        # Обновляем БД
        new_qty = storage.use_speedup(
            emu_id, speedup_type, denomination
        )
        db_qty = new_qty

        # Определяем контекст клика
        is_last_of_this_denom = (new_qty <= 0)
        is_last_click = (i == max_clicks - 1)

        # ── Пауза после клика ──
        # Последний клик (по номиналу или по плану) → дольше ждём
        if is_last_of_this_denom or is_last_click:
            time.sleep(DELAY_AFTER_LAST_USE)
        else:
            time.sleep(DELAY_AFTER_USE)

        # ── Проверяем завершение ПОСЛЕ КАЖДОГО клика ──
        completed = _check_confirm_or_completed(emulator, context)
        if completed:
            return used, True

        # Если номинал закончился → строки сдвинулись → выходим
        if is_last_of_this_denom:
            logger.debug(
                f"[{emu_name}] 🔄 Номинал закончился, "
                f"строки сдвинулись — нужен rescan"
            )
            break

    return used, False


# ═══════════════════════════════════════════════════
# ОБРАБОТКА ЗАВЕРШЕНИЯ
# ═══════════════════════════════════════════════════

def _check_confirm_or_completed(
    emulator: Dict,
    context: str
) -> bool:
    """
    Проверить: улучшение завершилось?

    Два варианта:
    1. Появилась кнопка "Подтвердить" (номинал сильно превысил таймер)
       → кликаем → завершено
    2. Окно закрылось автоматически → проверяем контекстный маркер

    Returns:
        True если улучшение завершено
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    # Проверяем кнопку "Подтвердить"
    confirm_path = TEMPLATES['button_confirm']
    if os.path.exists(confirm_path):
        confirm = find_image(
            emulator, confirm_path, threshold=THRESHOLD_TEMPLATE
        )
        if confirm:
            cx, cy = confirm
            logger.info(f"[{emu_name}] ✅ Кнопка 'Подтвердить' найдена, кликаем")
            tap(emulator, x=cx, y=cy)
            time.sleep(DELAY_AFTER_CONFIRM)

            # После подтверждения: проверяем контекстный маркер
            return _check_context_completion(emulator, context)

    # Нет "Подтвердить" → проверяем, не закрылось ли окно само
    return _check_context_completion(emulator, context)


def _check_context_completion(
    emulator: Dict,
    context: str
) -> bool:
    """
    Проверить контекст-специфичный маркер завершения.

    - building:  navigation_icon (панель навигации видна = окно закрылось)
    - training:  button_training (кнопка "Обучение" = вернулись к тренировке)
    - evolution: evolution_close_x (крестик = закрылись оба окна)

    Returns:
        True если маркер найден (улучшение завершено)
    """
    template_key = {
        'building': 'navigation_icon',
        'training': 'button_training',
        'evolution': 'evolution_close_x',
    }.get(context)

    if template_key is None:
        return False

    template_path = TEMPLATES.get(template_key)
    if not template_path or not os.path.exists(template_path):
        return False

    result = find_image(
        emulator, template_path, threshold=THRESHOLD_TEMPLATE
    )

    if result:
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        logger.info(
            f"[{emu_name}] 🏁 Маркер завершения ({template_key}) найден"
        )

    return result is not None


# ═══════════════════════════════════════════════════
# АЛМАЗНЫЙ ФИНИШ
# ═══════════════════════════════════════════════════

def _try_diamond_finish(
    emulator: Dict,
    ocr: OCREngine,
    context: str,
    result: DrainResult,
) -> bool:
    """
    Попытка завершить улучшение за алмазы.

    Условия:
    - Оставшееся время ≤ 22 мин
    - Стоимость ≤ 70 алмазов
    - Текущие алмазы ≥ стоимости

    Перед нажатием: 2 свайпа назад к стартовой позиции
    (кнопка "Завершить Сейчас" видна только в начале).

    Returns:
        True если завершение прошло успешно
    """
    emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    logger.debug(f"[{emu_name}] 💎 Попытка алмазного финиша")

    # ── Возврат к стартовой позиции ──
    _do_swipe_to_start(emulator)

    # ── Парсинг текущих алмазов ──
    current_diamonds = _parse_current_diamonds(emulator, ocr)
    if current_diamonds is None:
        logger.warning(f"[{emu_name}] ⚠️ Не удалось спарсить алмазы")
        return False

    # ── Парсинг стоимости на кнопке ──
    diamond_cost = _parse_diamond_cost(emulator, ocr)
    if diamond_cost is None:
        logger.warning(f"[{emu_name}] ⚠️ Не удалось спарсить стоимость алмазов")
        return False

    logger.info(
        f"[{emu_name}] 💎 Алмазы: текущие={current_diamonds}, "
        f"стоимость={diamond_cost}"
    )

    # ── Проверки ──
    if diamond_cost > DIAMOND_MAX_COST:
        logger.info(
            f"[{emu_name}] 💎 Стоимость {diamond_cost} > {DIAMOND_MAX_COST}, "
            f"алмазный финиш не выгоден"
        )
        return False

    if current_diamonds < diamond_cost:
        logger.info(
            f"[{emu_name}] 💎 Недостаточно алмазов: "
            f"{current_diamonds} < {diamond_cost}"
        )
        return False

    # ── Клик "Завершить Сейчас" ──
    tap(emulator, *COORD_DIAMOND_BUTTON)
    time.sleep(DELAY_AFTER_LAST_USE)

    result.diamonds_used = diamond_cost

    # ── Проверяем "Подтвердить" или автозакрытие ──
    completed = _check_confirm_or_completed(emulator, context)
    if completed:
        return True

    # Если не нашли маркер — возможно всё равно сработало
    # (проверяем ещё раз после паузы)
    time.sleep(1.0)
    return _check_context_completion(emulator, context)


def _parse_current_diamonds(
    emulator: Dict,
    ocr: OCREngine
) -> Optional[int]:
    """
    Парсинг текущего кол-ва алмазов через OCR.

    Область: (414, 30, 488, 51)
    Формат: "14,800" → 14800 / "83,002" → 83002

    Returns:
        int или None
    """
    import cv2

    screenshot = get_screenshot(emulator)
    if screenshot is None:
        return None

    x1, y1, x2, y2 = AREA_DIAMONDS
    crop = screenshot[y1:y2, x1:x2]

    if crop.size == 0:
        return None

    # Увеличиваем для OCR
    scale = 5
    enlarged = cv2.resize(
        crop, None, fx=scale, fy=scale,
        interpolation=cv2.INTER_CUBIC
    )
    padding = 20
    padded = cv2.copyMakeBorder(
        enlarged, padding, padding, padding, padding,
        cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )

    elements = ocr.recognize_text(padded, min_confidence=0.3)
    if not elements:
        return None

    text = ''.join(e['text'].strip() for e in elements)
    # Удаляем всё кроме цифр и запятой
    cleaned = re.sub(r'[^\d,]', '', text)
    # Убираем запятые (формат разделителя тысяч)
    cleaned = cleaned.replace(',', '')

    if not cleaned:
        return None

    try:
        return int(cleaned)
    except ValueError:
        logger.warning(f"  _parse_current_diamonds: '{text}' → '{cleaned}' → ошибка")
        return None


def _parse_diamond_cost(
    emulator: Dict,
    ocr: OCREngine
) -> Optional[int]:
    """
    Парсинг стоимости алмазов на кнопке "Завершить Сейчас".

    Кнопка с алмазами находится в области около (475, 248).
    Стоимость — число на оранжевой кнопке справа.

    Парсим OCR в области кнопки с небольшим запасом.

    Returns:
        int стоимость или None
    """
    import cv2

    screenshot = get_screenshot(emulator)
    if screenshot is None:
        return None

    # Область кнопки с алмазами (примерная)
    # Из скриншота: иконка алмазов + число ~430-510, y ~235-260
    x1, y1, x2, y2 = 430, 230, 510, 265
    crop = screenshot[y1:y2, x1:x2]

    if crop.size == 0:
        return None

    scale = 5
    enlarged = cv2.resize(
        crop, None, fx=scale, fy=scale,
        interpolation=cv2.INTER_CUBIC
    )
    padding = 20
    padded = cv2.copyMakeBorder(
        enlarged, padding, padding, padding, padding,
        cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )

    elements = ocr.recognize_text(padded, min_confidence=0.3)
    if not elements:
        return None

    text = ''.join(e['text'].strip() for e in elements)
    cleaned = re.sub(r'[^\d]', '', text)

    if not cleaned:
        return None

    try:
        return int(cleaned)
    except ValueError:
        return None


# ═══════════════════════════════════════════════════
# ПАРСИНГ ТАЙМЕРА
# ═══════════════════════════════════════════════════

def _parse_remaining_timer(
    emulator: Dict,
    ocr: OCREngine,
    context: str
) -> Optional[int]:
    """
    Парсинг оставшегося таймера из окна ускорений.

    Формат: "00:02:44" → 164 сек / "1:10:41:48" → 124908 сек

    Returns:
        int секунды или None
    """
    import cv2

    area = TIMER_AREAS.get(context)
    if area is None:
        return None

    screenshot = get_screenshot(emulator)
    if screenshot is None:
        return None

    x1, y1, x2, y2 = area
    crop = screenshot[y1:y2, x1:x2]

    if crop.size == 0:
        return None

    scale = 5
    enlarged = cv2.resize(
        crop, None, fx=scale, fy=scale,
        interpolation=cv2.INTER_CUBIC
    )
    padding = 20
    padded = cv2.copyMakeBorder(
        enlarged, padding, padding, padding, padding,
        cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )

    elements = ocr.recognize_text(padded, min_confidence=0.3)
    if not elements:
        return None

    text = ''.join(e['text'].strip() for e in elements)
    return _parse_timer_text(text)


def _parse_timer_text(text: str) -> Optional[int]:
    """
    Конвертация текста таймера в секунды.

    Форматы:
        "00:02:44"     → 164  (ч:мин:сек)
        "1:10:41:48"   → 124908 (дн:ч:мин:сек)
        "02:44"        → 164  (мин:сек)

    Returns:
        int секунды или None
    """
    # Очищаем от мусора, оставляем цифры и двоеточия
    cleaned = re.sub(r'[^\d:]', '', text)

    if not cleaned:
        return None

    parts = cleaned.split(':')

    try:
        if len(parts) == 4:
            # дн:ч:мин:сек
            d, h, m, s = [int(p) for p in parts]
            return d * 86400 + h * 3600 + m * 60 + s
        elif len(parts) == 3:
            # ч:мин:сек
            h, m, s = [int(p) for p in parts]
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            # мин:сек
            m, s = [int(p) for p in parts]
            return m * 60 + s
        else:
            return None
    except (ValueError, IndexError):
        return None


# ═══════════════════════════════════════════════════
# СВАЙПЫ
# ═══════════════════════════════════════════════════

def _do_swipe_down(emulator: Dict):
    """Свайп вниз (к крупным/universal номиналам)."""
    s = SWIPE_DOWN
    swipe(emulator, s['x1'], s['y1'], s['x2'], s['y2'], s['duration'])
    time.sleep(DELAY_AFTER_SWIPE)


def _do_swipe_to_start(emulator: Dict):
    """
    Возврат к стартовой позиции — 2 свайпа назад.

    После этого "Завершить Сейчас" снова видна наверху.
    """
    s = SWIPE_BACK
    for _ in range(2):
        swipe(emulator, s['x1'], s['y1'], s['x2'], s['y2'], s['duration'])
        time.sleep(DELAY_AFTER_SWIPE)