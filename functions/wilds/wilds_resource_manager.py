"""
Менеджер ресурсов для охоты на диких существ

Функции:
- Парсинг складов ресурсов (клик по панели → OCR → ESC)
- Алгоритм приоритизации и распределения атак
- Построение hunt_plan для всей сессии

Координаты панели ресурсов (верхняя панель в поместье):
  Яблоки (43, 19), Листья (199, 19), Грунт (348, 19), Песок (426, 19)
  Мёд — не парсим (нет ограничений по складу)

Формат строки "Сохранено": 783.8К/17.5М или 783.8К/830.0К
  К = тысячи (0.0К – 999.9К)
  М = миллионы (1.0М – 999.9М), 100.0К = 0.1М

Версия: 2.0
Дата обновления: 2025-03-11
Изменения:
- analyze_and_prioritize() заменён на build_hunt_plan()
- Добавлен алгоритм распределения атак по ресурсам
- Планирование всей сессии за один вызов
"""

import math
import re
import time
from typing import Dict, List, Optional, Tuple
from utils.adb_controller import tap, press_key
from utils.image_recognition import get_screenshot
from utils.ocr_engine import OCREngine
from utils.config_manager import load_config
from utils.logger import logger
from functions.wilds.wilds_database import (
    WildsDatabase, RESOURCE_NAMES_RU, WILD_LOOT
)


# Координаты кликов по ресурсам на верхней панели
RESOURCE_PANEL_COORDS = {
    'apples': (43, 19),
    'leaves': (199, 19),
    'soil':   (348, 19),
    'sand':   (426, 19),
}

# Порядок парсинга (без мёда — у него нет склада)
PARSEABLE_RESOURCES = ['apples', 'leaves', 'soil', 'sand']

# Ресурсы которые есть в GUI (включая мёд)
ALL_RESOURCE_KEYS = ['apples', 'leaves', 'soil', 'sand', 'honey']

# Приоритетные ресурсы для фарма до 85% (порядок имеет значение)
PRIORITY_RESOURCES = ['sand', 'soil']

# Пороги заполнения складов (в процентах)
THRESHOLD_LOW = 50
THRESHOLD_HIGH = 85


class WildsResourceManager:
    """
    Менеджер ресурсов для охоты на диких

    Использование:
        manager = WildsResourceManager()
        plan = manager.build_hunt_plan(emulator, emu_id, total_attacks=16, wild_level=12)
        # plan = [{'resource': 'sand', 'attempts': 8}, {'resource': 'soil', 'attempts': 8}]
    """

    # Область OCR для парсинга строки "Сохранено" после клика по ресурсу
    # Формат: (x1, y1, x2, y2)
    OCR_REGION_STORED = (0, 250, 540, 700)
    Y_TOLERANCE = 20

    def __init__(self):
        self.db = WildsDatabase()
        self._ocr = None

    @property
    def ocr(self) -> OCREngine:
        """Ленивая инициализация OCR"""
        if self._ocr is None:
            self._ocr = OCREngine(lang='ru')
        return self._ocr

    # ==================== ГЛАВНЫЙ МЕТОД ====================

    def build_hunt_plan(
        self,
        emulator: Dict,
        emulator_id: int,
        total_attacks: int,
        wild_level: int
    ) -> List[Dict]:
        """
        Спарсить склады и построить план охоты на всю сессию

        Предусловие: бот внутри поместья (видит панель ресурсов)

        Алгоритм:
        1. Загрузить включённые ресурсы из GUI
        2. Спарсить склады (клик → OCR → ESC для каждого)
        3. Рассчитать loot_per_attack по уровню дикого
        4. Распределить total_attacks по приоритетам:
           P1: ресурсы < 50% → фармить до 50%
           P2: песок, грунт → фармить до 85%
           P3: мёд (если всё ≥ 85%)
           P4: наименее заполненный (fallback)

        Args:
            emulator: dict эмулятора
            emulator_id: ID эмулятора
            total_attacks: суммарное число доступных атак
            wild_level: уровень дикого (1-15)

        Returns:
            [{'resource': 'sand', 'attempts': 8}, ...]
            Пустой список если нет смысла охотиться
        """
        emu_name = emulator.get('name', '?')

        # 1. Загрузить включённые ресурсы
        enabled = self._load_enabled_resources(emulator_id)
        if not enabled:
            logger.warning(f"[{emu_name}] ⚠️ Нет включённых ресурсов для охоты")
            return []

        logger.info(
            f"[{emu_name}] 📊 Планирование охоты: "
            f"атак={total_attacks}, ур.дикого={wild_level}"
        )

        # 2. Спарсить склады (только парсируемые: без мёда)
        storage_data = self._parse_all_storages(emulator, emulator_id, enabled)

        # 3. Honey включён?
        honey_enabled = 'honey' in enabled

        # 4. Loot за 1 атаку (в тысячах K)
        loot = WILD_LOOT.get(wild_level, WILD_LOOT.get(1, 11.2))

        # 5. Распределить атаки
        plan = self._distribute_attacks(
            storage_data, total_attacks, loot, honey_enabled
        )

        # Логируем план
        if plan:
            parts = []
            for p in plan:
                name = RESOURCE_NAMES_RU.get(p['resource'], p['resource'])
                parts.append(f"{name}:{p['attempts']}")
            logger.info(
                f"[{emu_name}] 📋 План охоты: [{', '.join(parts)}] "
                f"(всего атак: {total_attacks})"
            )
        else:
            logger.info(f"[{emu_name}] 📋 Охота не нужна — склады полные")

        return plan

    # ==================== РАСПРЕДЕЛЕНИЕ АТАК ====================

    def _distribute_attacks(
        self,
        storage_data: Dict,
        total_attacks: int,
        loot: float,
        honey_enabled: bool
    ) -> List[Dict]:
        """
        Распределить атаки по ресурсам согласно приоритетам ТЗ

        Args:
            storage_data: {resource: {stored, capacity, fill_pct}}
            total_attacks: суммарное число атак
            loot: добыча за 1 атаку (K)
            honey_enabled: мёд включён в GUI

        Returns:
            [{'resource': 'sand', 'attempts': 8}, ...]
        """
        allocated = {}  # {resource: attempts}
        remaining = total_attacks

        if remaining <= 0 or (not storage_data and not honey_enabled):
            return []

        # ===== P1: ресурсы < 50% → фармить до 50% (самый отстающий первым) =====
        under_50 = [
            (res, data) for res, data in storage_data.items()
            if data['fill_pct'] < THRESHOLD_LOW
        ]
        under_50.sort(key=lambda x: x[1]['fill_pct'])

        for res, data in under_50:
            if remaining <= 0:
                break
            target_stored = data['capacity'] * THRESHOLD_LOW / 100
            deficit = target_stored - data['stored']
            if deficit <= 0:
                continue
            needed = math.ceil(deficit / loot)
            to_allocate = min(needed, remaining)
            allocated[res] = allocated.get(res, 0) + to_allocate
            remaining -= to_allocate

        # ===== P2: песок и грунт до 85% =====
        if remaining > 0:
            for res in PRIORITY_RESOURCES:
                if remaining <= 0:
                    break
                if res not in storage_data:
                    continue

                data = storage_data[res]
                target_stored = data['capacity'] * THRESHOLD_HIGH / 100
                # Учитываем уже запланированные атаки
                already = allocated.get(res, 0)
                projected = data['stored'] + already * loot
                deficit = target_stored - projected
                if deficit <= 0:
                    continue
                needed = math.ceil(deficit / loot)
                to_allocate = min(needed, remaining)
                allocated[res] = allocated.get(res, 0) + to_allocate
                remaining -= to_allocate

        # ===== P3: мёд если ВСЕ спроецированные ≥ 85% =====
        if remaining > 0 and honey_enabled:
            all_high = True
            for res, data in storage_data.items():
                already = allocated.get(res, 0)
                projected = data['stored'] + already * loot
                projected_pct = projected / data['capacity'] * 100 if data['capacity'] > 0 else 100
                if projected_pct < THRESHOLD_HIGH:
                    all_high = False
                    break

            if all_high:
                allocated['honey'] = allocated.get('honey', 0) + remaining
                remaining = 0

        # ===== P4: fallback — наименее заполненный =====
        if remaining > 0:
            if storage_data:
                # Находим наименее заполненный с учётом уже запланированного
                candidates = []
                for res, data in storage_data.items():
                    already = allocated.get(res, 0)
                    projected = data['stored'] + already * loot
                    projected_pct = projected / data['capacity'] * 100 if data['capacity'] > 0 else 100
                    candidates.append((res, projected_pct))

                candidates.sort(key=lambda x: x[1])
                least_filled = candidates[0][0]
                allocated[least_filled] = allocated.get(least_filled, 0) + remaining
                remaining = 0
            elif honey_enabled:
                allocated['honey'] = allocated.get('honey', 0) + remaining
                remaining = 0

        # Конвертируем в список (сохраняем порядок приоритетов)
        result = []
        for res, att in allocated.items():
            if att > 0:
                result.append({'resource': res, 'attempts': att})
        return result

    # ==================== ПАРСИНГ СКЛАДОВ ====================

    def _parse_all_storages(
        self,
        emulator: Dict,
        emulator_id: int,
        enabled: List[str]
    ) -> Dict:
        """
        Спарсить все включённые склады ресурсов

        Предусловие: бот в поместье

        Для каждого ресурса: клик → OCR → ESC

        Returns:
            {resource: {'stored': float, 'capacity': float, 'fill_pct': float}}
        """
        emu_name = emulator.get('name', '?')
        storage_data = {}

        for res in PARSEABLE_RESOURCES:
            if res not in enabled:
                continue

            coords = RESOURCE_PANEL_COORDS.get(res)
            if not coords:
                continue

            res_name = RESOURCE_NAMES_RU.get(res, res)
            logger.debug(f"[{emu_name}] 📦 Парсинг склада: {res_name}")

            # Клик по ресурсу на панели
            tap(emulator, *coords)
            time.sleep(1.5)

            # Парсинг "Сохранено"
            stored, capacity = self._parse_stored_line(emulator)

            # Закрыть окно ресурса
            press_key(emulator, "ESC")
            time.sleep(0.8)

            if stored is not None and capacity is not None and capacity > 0:
                fill_pct = stored / capacity * 100
                storage_data[res] = {
                    'stored': stored,
                    'capacity': capacity,
                    'fill_pct': fill_pct,
                }
                # Записать в БД
                self.db.update_resource(emulator_id, res, stored, capacity)
                logger.info(
                    f"[{emu_name}] 📦 {res_name}: "
                    f"{stored:.1f}K / {capacity:.1f}K ({fill_pct:.0f}%)"
                )
            else:
                logger.warning(
                    f"[{emu_name}] ⚠️ Не удалось спарсить склад: {res_name}"
                )

        return storage_data

    def _parse_stored_line(self, emulator: Dict) -> Tuple[Optional[float], Optional[float]]:
        """
        Спарсить строку "Сохранено" из всплывающего окна ресурса.

        Алгоритм:
        1. OCR по широкой области всего всплывающего окна
        2. Найти элемент содержащий "Сохранено" (или похожее)
        3. По Y этого элемента найти значение (другой элемент на той же строке)
        4. Распарсить формат: 783.8К/17.5М или 6.0M/6.0M

        Returns:
            (stored_k, capacity_k) — оба в тысячах (K)
            (None, None) если парсинг не удался
        """
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None, None

        # 1. OCR по широкой области
        elements = self.ocr.recognize_text(
            screenshot,
            region=self.OCR_REGION_STORED,
            min_confidence=0.3
        )

        if not elements:
            logger.debug("  Stored: OCR не нашёл текста в области окна")
            return None, None

        # Логируем все найденные элементы для отладки
        for e in elements:
            logger.debug(
                f"  OCR elem: '{e.get('text', '')}' "
                f"y={e.get('y', '?')} x={e.get('x', '?')}"
            )

        # 2. Найти элемент "Сохранено"
        stored_elem = None
        for e in elements:
            text = e.get('text', '').strip()
            # Толерантный поиск: "Сохранено", "Сохранен", "Cохранено" (лат C)
            if re.search(r'[СсCc]охранен', text, re.IGNORECASE):
                stored_elem = e
                break

        if stored_elem is None:
            all_texts = [e.get('text', '') for e in elements]
            logger.debug(
                f"  Stored: слово 'Сохранено' не найдено. "
                f"Все тексты: {all_texts}"
            )
            return None, None

        stored_y = stored_elem.get('y', 0)
        logger.debug(
            f"  Stored: найдено 'Сохранено' на Y={stored_y}"
        )

        # 3. Найти значение на той же строке (по Y ± допуск)
        #    Значение — это другой элемент правее, содержащий цифры и K/M
        value_text = None
        for e in elements:
            if e is stored_elem:
                continue
            if abs(e.get('y', 0) - stored_y) <= self.Y_TOLERANCE:
                candidate = e.get('text', '').strip()
                # Проверяем что это похоже на значение (содержит цифры и слэш или K/M)
                if re.search(r'\d', candidate) and (
                    '/' in candidate
                    or re.search(r'[КKкkМMмm]', candidate)
                ):
                    value_text = candidate
                    logger.debug(f"  Stored: значение на той же строке: '{value_text}'")
                    break

        # 4. Если не нашли отдельный элемент — может быть в самом "Сохранено"
        #    Например OCR мог склеить: "Сохранено 6.0M/6.0M"
        if value_text is None:
            full_stored_text = stored_elem.get('text', '')
            if re.search(r'\d', full_stored_text) and '/' in full_stored_text:
                value_text = full_stored_text
                logger.debug(
                    f"  Stored: значение внутри элемента 'Сохранено': '{value_text}'"
                )

        if value_text is None:
            logger.debug(
                f"  Stored: не найдено значение рядом с 'Сохранено' (Y={stored_y})"
            )
            return None, None

        # 5. Парсинг значения
        return self._parse_resource_value(value_text)

    def _parse_resource_value(self, text: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Распарсить строку вида '6.0M/6.0M', '783.8К/17.5М', '1.4M/14.5M'

        Поддерживает:
        - Кириллицу (К, М) и латиницу (K, M)
        - Точки и запятые как разделитель дробной части
        - Пробелы вокруг слэша

        Returns:
            (stored_k, capacity_k) — оба в тысячах (K)
            (None, None) если не удалось
        """
        # Нормализация
        normalized = text.replace(',', '.').replace(' ', '')

        # Паттерн: число + единица / число + единица
        pattern = r'(\d+\.?\d*)\s*([КKкkМMмm])\s*/\s*(\d+\.?\d*)\s*([КKкkМMмm])'
        match = re.search(pattern, normalized)

        if not match:
            # Попробуем с оригинальным текстом (без удаления пробелов)
            match = re.search(pattern, text.replace(',', '.'))

        if not match:
            logger.debug(f"  Stored: regex не сматчил '{text}'")
            return None, None

        val1_str, unit1, val2_str, unit2 = match.groups()

        try:
            stored = self._to_thousands(float(val1_str), unit1)
            capacity = self._to_thousands(float(val2_str), unit2)
            logger.debug(
                f"  Stored: parsed {stored:.1f}K / {capacity:.1f}K"
            )
            return stored, capacity
        except (ValueError, TypeError) as e:
            logger.debug(f"  Stored: ошибка конвертации: {e}")
            return None, None

    # ==================== УТИЛИТЫ ====================

    @staticmethod
    def _to_thousands(value: float, unit: str) -> float:
        """
        Привести значение к тысячам (K)

        К/K → value (уже в тысячах)
        М/M → value * 1000 (миллионы → тысячи)
        """
        unit_upper = unit.upper()
        if unit_upper in ('К', 'K'):
            return value
        elif unit_upper in ('М', 'M'):
            return value * 1000
        return value

    @staticmethod
    def _load_enabled_resources(emulator_id: int) -> List[str]:
        """
        Загрузить список включённых ресурсов из gui_config.yaml

        Returns:
            ['apples', 'leaves', 'soil', 'sand', 'honey'] — только включённые
        """
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(emulator_id)
        settings = emu_settings.get(emu_key, {})
        wilds = settings.get("wilds", {})
        resources = wilds.get("resources", {})

        # По умолчанию все ресурсы включены
        enabled = []
        for res_key in ALL_RESOURCE_KEYS:
            if resources.get(res_key, True):
                enabled.append(res_key)

        return enabled