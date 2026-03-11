"""
Менеджер ресурсов для охоты на диких существ

Функции:
- Парсинг складов ресурсов (клик по панели → OCR → ESC)
- Алгоритм приоритизации: какой ресурс фармить первым
- Запись состояния складов в БД

Координаты панели ресурсов (верхняя панель в поместье):
  Яблоки (43, 19), Листья (199, 19), Грунт (348, 19), Песок (426, 19)
  Мёд — не парсим (нет ограничений по складу)

Формат строки "Сохранено": 783.8К/17.5М или 783.8К/830.0К
  К = тысячи (0.0К – 999.9К)
  М = миллионы (1.0М – 999.9М), 100.0К = 0.1М

Версия: 1.0
Дата создания: 2025-03-11
"""

import re
import time
from typing import Dict, List, Optional, Tuple
from utils.adb_controller import tap, press_key
from utils.image_recognition import get_screenshot
from utils.ocr_engine import OCREngine
from utils.config_manager import load_config
from utils.logger import logger
from functions.wilds.wilds_database import WildsDatabase, RESOURCE_NAMES_RU


# Координаты кликов по ресурсам на верхней панели
RESOURCE_PANEL_COORDS = {
    'apples': (43, 19),
    'leaves': (199, 19),
    'soil':   (348, 19),
    'sand':   (426, 19),
    # honey — не парсим, нет ограничений
}

# Порядок парсинга (без мёда)
PARSEABLE_RESOURCES = ['apples', 'leaves', 'soil', 'sand']

# Приоритетные ресурсы для фарма до 85%
PRIORITY_RESOURCES = ['sand', 'soil']

# Пороги заполнения складов (в процентах)
THRESHOLD_LOW = 50      # Ниже — срочно фармить
THRESHOLD_HIGH = 85     # Выше — склад почти полный


class WildsResourceManager:
    """
    Менеджер ресурсов для охоты на диких

    Использование:
        manager = WildsResourceManager()
        resource_queue = manager.analyze_and_prioritize(emulator, emulator_id)
        # resource_queue = ['sand', 'soil', 'apples'] — в порядке приоритета
    """

    # Область OCR для парсинга строки "Сохранено" после клика по ресурсу
    # Подбирается экспериментально — область где появляется текст склада
    # Формат: (x1, y1, x2, y2)
    OCR_REGION_STORED = (0, 70, 540, 130)  # TODO: уточнить по скриншоту

    def __init__(self):
        self.db = WildsDatabase()
        self._ocr = None  # Ленивая инициализация

    @property
    def ocr(self) -> OCREngine:
        """Ленивая инициализация OCR (тяжёлый объект)"""
        if self._ocr is None:
            self._ocr = OCREngine(lang='ru')
        return self._ocr

    # ==================== ГЛАВНЫЙ МЕТОД ====================

    def analyze_and_prioritize(
        self,
        emulator: Dict,
        emulator_id: int
    ) -> List[str]:
        """
        Спарсить склады и определить порядок фарма ресурсов

        Предусловие: бот внутри поместья (видит панель ресурсов)

        Алгоритм:
        1. Загрузить настройки включённых ресурсов из GUI
        2. Для каждого включённого ресурса (кроме мёда):
           - Клик по ресурсу → парсинг "Сохранено" → ESC
           - Запись в БД
        3. Применить алгоритм приоритизации
        4. Вернуть упорядоченный список ресурсов

        Args:
            emulator: dict эмулятора
            emulator_id: ID эмулятора

        Returns:
            list: ресурсы в порядке приоритета, например ['sand', 'soil']
                  Пустой список если все склады полные или все ресурсы выключены
        """
        emu_name = emulator.get('name', f"id:{emulator_id}")

        # 1. Загрузить включённые ресурсы из настроек
        enabled = self._get_enabled_resources(emulator_id)
        if not enabled:
            logger.warning(f"[{emu_name}] ⚠️ Все ресурсы выключены в настройках")
            return []

        logger.info(
            f"[{emu_name}] 📊 Парсинг складов: "
            f"{', '.join(RESOURCE_NAMES_RU.get(r, r) for r in enabled)}"
        )

        # 2. Парсинг каждого ресурса (кроме мёда)
        resources_data = {}  # {resource_key: {stored, capacity, fill_pct}}

        for res_key in PARSEABLE_RESOURCES:
            if res_key not in enabled:
                continue

            result = self._parse_single_resource(emulator, emulator_id, res_key)
            if result:
                resources_data[res_key] = result

        if not resources_data:
            logger.warning(f"[{emu_name}] ⚠️ Не удалось спарсить ни одного ресурса")
            return []

        # Логируем состояние складов
        self._log_storage_status(emu_name, resources_data)

        # 3. Приоритизация
        honey_enabled = 'honey' in enabled
        queue = self._prioritize(resources_data, honey_enabled)

        if queue:
            names = [RESOURCE_NAMES_RU.get(r, r) for r in queue]
            logger.info(f"[{emu_name}] 🎯 Порядок фарма: {' → '.join(names)}")
        else:
            logger.info(f"[{emu_name}] ✅ Все склады заполнены, фарм не нужен")

        return queue

    # ==================== ПАРСИНГ ОДНОГО РЕСУРСА ====================

    def _parse_single_resource(
        self,
        emulator: Dict,
        emulator_id: int,
        resource_key: str
    ) -> Optional[Dict]:
        """
        Кликнуть по ресурсу, спарсить склад, ESC

        Returns:
            dict: {stored, capacity, fill_pct} или None при ошибке
        """
        emu_name = emulator.get('name', f"id:{emulator_id}")
        res_name = RESOURCE_NAMES_RU.get(resource_key, resource_key)
        coords = RESOURCE_PANEL_COORDS.get(resource_key)

        if not coords:
            logger.error(f"[{emu_name}] ❌ Нет координат для ресурса {resource_key}")
            return None

        # Клик по ресурсу
        tap(emulator, coords[0], coords[1])
        time.sleep(1.5)

        # Получить скриншот и распознать текст
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            logger.error(f"[{emu_name}] ❌ Не удалось получить скриншот для {res_name}")
            press_key(emulator, "ESC")
            time.sleep(0.5)
            return None

        # OCR в области "Сохранено"
        elements = self.ocr.recognize_text(
            screenshot,
            region=self.OCR_REGION_STORED,
            min_confidence=0.3
        )

        # Парсим текст
        stored, capacity = self._extract_stored_values(elements, emu_name, res_name)

        # ESC — закрыть окно ресурса
        press_key(emulator, "ESC")
        time.sleep(0.5)

        if stored is None or capacity is None:
            logger.warning(
                f"[{emu_name}] ⚠️ Не удалось спарсить {res_name}"
            )
            return None

        # Записать в БД
        self.db.update_resource(emulator_id, resource_key, stored, capacity)

        fill_pct = (stored / capacity * 100) if capacity > 0 else 0

        return {
            'stored': stored,
            'capacity': capacity,
            'fill_pct': fill_pct,
        }

    def _extract_stored_values(
        self,
        elements: list,
        emu_name: str,
        res_name: str
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Извлечь stored и capacity из OCR-элементов

        Ищем текст в формате: 783.8К/17.5М или 783.8К/830.0К
        Возвращаем оба значения в ТЫСЯЧАХ (K)

        Returns:
            (stored_k, capacity_k) или (None, None)
        """
        # Собрать весь текст из элементов
        full_text = ' '.join(e.get('text', '') for e in elements)

        logger.debug(f"[{emu_name}] OCR raw ({res_name}): '{full_text}'")

        # Паттерн: число с K/М слеш число с K/М
        # Примеры: 783.8К/17.5М, 783.8К/830.0К, 0.0К/830.0К
        # Учитываем и латинские K/M и кириллические К/М
        pattern = r'(\d+[\.,]\d+)\s*([КкKkМмMm])\s*/\s*(\d+[\.,]\d+)\s*([КкKkМмMm])'

        match = re.search(pattern, full_text)
        if not match:
            # Попытка без дробной части: 0К/830К
            pattern_int = r'(\d+)\s*([КкKkМмMm])\s*/\s*(\d+[\.,]?\d*)\s*([КкKkМмMm])'
            match = re.search(pattern_int, full_text)

        if not match:
            logger.warning(
                f"[{emu_name}] ⚠️ Паттерн склада не найден в: '{full_text}'"
            )
            return None, None

        stored_num = float(match.group(1).replace(',', '.'))
        stored_unit = match.group(2).upper()
        capacity_num = float(match.group(3).replace(',', '.'))
        capacity_unit = match.group(4).upper()

        # Нормализация единиц: К/K → тысячи, М/M → миллионы → тысячи
        stored_k = self._to_thousands(stored_num, stored_unit)
        capacity_k = self._to_thousands(capacity_num, capacity_unit)

        logger.debug(
            f"[{emu_name}] 📦 {res_name}: "
            f"{stored_k:.1f}K / {capacity_k:.1f}K "
            f"({stored_k / capacity_k * 100:.0f}%)"
        )

        return stored_k, capacity_k

    @staticmethod
    def _to_thousands(value: float, unit: str) -> float:
        """
        Конвертировать значение в тысячи (K)

        К/K → уже в тысячах
        М/M → умножить на 1000

        Args:
            value: числовое значение
            unit: единица ('К', 'K', 'М', 'M' и т.д.)

        Returns:
            float: значение в тысячах
        """
        # Нормализуем: кириллические и латинские → единый формат
        unit_upper = unit.upper()

        if unit_upper in ('М', 'M', 'М'):
            return value * 1000.0  # Миллионы → тысячи
        else:
            return value  # Уже в тысячах

    # ==================== АЛГОРИТМ ПРИОРИТИЗАЦИИ ====================

    def _prioritize(
        self,
        resources_data: Dict[str, Dict],
        honey_enabled: bool
    ) -> List[str]:
        """
        Определить порядок фарма ресурсов

        Приоритеты:
        1. Ресурс < 50% → фармить (самый отстающий первым)
        2. Все >= 50% → фармить Песок/Грунт до 85%
        3. Все >= 85% → фармить Мёд (если включён)
        4. Мёд выключен и всё >= 85% → фармить наименее заполненный

        Args:
            resources_data: {resource_key: {stored, capacity, fill_pct}}
            honey_enabled: включён ли мёд в настройках

        Returns:
            list: ресурсы в порядке приоритета
        """
        if not resources_data:
            return []

        queue = []

        # ПРИОРИТЕТ 1: Ресурсы ниже 50% (самый отстающий первым)
        below_50 = [
            (key, data['fill_pct'])
            for key, data in resources_data.items()
            if data['fill_pct'] < THRESHOLD_LOW
        ]

        if below_50:
            # Сортируем по заполненности (меньше → приоритетнее)
            below_50.sort(key=lambda x: x[1])
            queue.extend(key for key, _ in below_50)

            # Добавляем остальные ресурсы тоже (если < 85%)
            remaining = [
                (key, data['fill_pct'])
                for key, data in resources_data.items()
                if key not in queue and data['fill_pct'] < THRESHOLD_HIGH
            ]
            remaining.sort(key=lambda x: x[1])
            queue.extend(key for key, _ in remaining)

            return queue

        # ПРИОРИТЕТ 2: Все >= 50%, но есть < 85% → Песок/Грунт в приоритете
        below_85 = {
            key: data['fill_pct']
            for key, data in resources_data.items()
            if data['fill_pct'] < THRESHOLD_HIGH
        }

        if below_85:
            # Сначала приоритетные (песок, грунт) если они < 85%
            for prio_key in PRIORITY_RESOURCES:
                if prio_key in below_85:
                    queue.append(prio_key)

            # Потом остальные < 85%
            for key in below_85:
                if key not in queue:
                    queue.append(key)

            return queue

        # ПРИОРИТЕТ 3: Все >= 85% → Мёд
        if honey_enabled:
            return ['honey']

        # ПРИОРИТЕТ 4: Мёд выключен, всё >= 85% → фармить наименее заполненный
        sorted_by_fill = sorted(
            resources_data.items(),
            key=lambda x: x[1]['fill_pct']
        )
        if sorted_by_fill:
            return [sorted_by_fill[0][0]]

        return []

    # ==================== ЗАГРУЗКА НАСТРОЕК ====================

    def _get_enabled_resources(self, emulator_id: int) -> List[str]:
        """
        Получить список включённых ресурсов из GUI настроек

        Returns:
            list: ['apples', 'leaves', 'soil', 'sand', 'honey'] — только включённые
        """
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(emulator_id)
        settings = emu_settings.get(emu_key, {})
        wilds = settings.get("wilds", {})
        resources = wilds.get("resources", {})

        # По умолчанию все включены
        enabled = []
        for res_key in ['apples', 'leaves', 'soil', 'sand', 'honey']:
            if resources.get(res_key, True):  # True по умолчанию
                enabled.append(res_key)

        return enabled

    # ==================== ЛОГИРОВАНИЕ ====================

    def _log_storage_status(
        self,
        emu_name: str,
        resources_data: Dict[str, Dict]
    ):
        """Красивый лог состояния складов"""
        parts = []
        for key in PARSEABLE_RESOURCES:
            if key not in resources_data:
                continue
            data = resources_data[key]
            name = RESOURCE_NAMES_RU.get(key, key)
            pct = data['fill_pct']

            # Иконка уровня заполнения
            if pct >= THRESHOLD_HIGH:
                icon = "🟢"
            elif pct >= THRESHOLD_LOW:
                icon = "🟡"
            else:
                icon = "🔴"

            parts.append(f"{icon} {name}: {pct:.0f}%")

        logger.info(f"[{emu_name}] 📊 Склады: {' | '.join(parts)}")