"""
Навигация для сбора ресурсов с плиток

Обеспечивает полный цикл отправки одного отряда на плитку:
1. Лупа (карта мира) → клик → окно поиска
2. Переход на вкладку ресурсов → выбор ресурса
3. Сброс/выбор уровня плитки
4. Поиск плитки (с повышением уровня если не найдена)
5. Клик "Собирать" → проверка "Походный Отряд"
6. Выбор отряда → клик "Отправить"

Также: настройка Листа 2 для формаций (слабые отряды для фарма)

Переиспользуемые компоненты из wilds:
- WildsNavigation.ensure_on_world_map()  — выход на карту мира
- WildsNavigation.ensure_in_estate()     — возврат в поместье
- Шаблон magnifying_glass               — маркер карты мира
- Шаблон march_squad_title              — заголовок "Походный Отряд"

Версия: 1.0
Дата создания: 2025-03-17
"""

import os
import time
from typing import Dict, Optional, Tuple

from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image
from utils.logger import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ==================== РУССКИЕ НАЗВАНИЯ ДЛЯ ЛОГОВ ====================
RESOURCE_NAMES_RU = {
    'apples': 'Яблоки',
    'leaves': 'Листья',
    'soil': 'Грунт',
    'sand': 'Песок',
}

SQUAD_NAMES_RU = {
    'special': 'Особый Отряд',
    'squad_1': 'Отряд I',
    'squad_2': 'Отряд II',
    'squad_3': 'Отряд III',
}


class TilesNavigation:
    """
    Навигация для отправки отрядов на плитки

    Методы:
    - send_squad_to_tile()  — полный цикл: лупа → поиск → ресурс → отряд → отправить
    - setup_sheet_2()       — переключить на Лист 2 (слабые отряды для фарма)
    """

    # ==================== ШАБЛОНЫ ====================

    TEMPLATES = {
        # Лупа — маркер карты мира (переиспользуем из wilds)
        'magnifying_glass': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'magnifying_glass.png'
        ),
        # Заголовок "Походный Отряд" (переиспользуем из wilds)
        'march_squad_title': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'march_squad_title.png'
        ),
        # Кнопка "Поиск" в окне поиска плиток
        'search_button': os.path.join(
            BASE_DIR, 'data', 'templates', 'tiles', 'search_button.png'
        ),
        # Иконка выбранного Листа 2
        'sheet_2_icon': os.path.join(
            BASE_DIR, 'data', 'templates', 'tiles', 'sheet_2_icon.png'
        ),
        # Иконка мечей (открывает "Походный Отряд") — из wilds
        'swords_icon': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'swords_icon.png'
        ),
        # Кнопка "Сменить Состав" — из wilds
        'change_squad_btn': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'change_squad_btn.png'
        ),
        # Кнопка "Пополнение Зверей" — из wilds
        'refill_beasts_btn': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'refill_beasts_btn.png'
        ),
        # Кнопка "Подтвердить" — из wilds
        'btn_confirm': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'btn_confirm.png'
        ),
    }

    # ==================== НАСТРОЙКИ ====================

    THRESHOLD_TEMPLATE = 0.8
    THRESHOLD_MAGNIFIER = 0.85

    MAX_SEARCH_RETRIES = 2       # Повторные попытки полного цикла поиска
    MAX_SHEET_ATTEMPTS = 2       # Попытки настроить Лист 2

    # ==================== КООРДИНАТЫ ====================

    # Окно поиска плиток (после клика по лупе)
    COORD_RESOURCE_TAB = (272, 935)  # Вкладка выбора ресурса

    # Сброс позиции ресурсов в стартовую точку
    SWIPE_RESET_START = (42, 762)
    SWIPE_RESET_END = (489, 762)
    SWIPE_RESET_COUNT = 3

    # Выбор ресурса: координаты после стартовой позиции
    RESOURCE_COORDS = {
        'apples': {'swipes_needed': 0, 'coord': (270, 725)},
        'leaves': {'swipes_needed': 0, 'coord': (447, 734)},
        'soil':   {'swipes_needed': 1, 'coord': (92, 723)},
        'sand':   {'swipes_needed': 1, 'coord': (273, 718)},
    }
    # Свайп для прокрутки к грунту/песку
    SWIPE_RESOURCE_START = (501, 760)
    SWIPE_RESOURCE_END = (27, 760)

    # Уровень плитки
    COORD_LEVEL_MINUS = (38, 849)
    COORD_LEVEL_PLUS = (352, 849)
    COORD_SEARCH = (452, 846)
    LEVEL_RESET_CLICKS = 17  # Кликов минус для гарантированного сброса до 1

    # Кнопка "Собирать"
    COORD_COLLECT = (315, 561)

    # Кнопка "Отправить"
    COORD_SEND = (393, 901)

    # Выбор отряда в окне "Походный Отряд"
    SQUAD_COORDS = {
        'special': {'needs_swipe': False, 'coord': (172, 440)},
        'squad_1': {'needs_swipe': False, 'coord': (172, 670)},
        'squad_2': {'needs_swipe': True,  'coord': (172, 440)},
        'squad_3': {'needs_swipe': True,  'coord': (172, 670)},
    }
    SWIPE_SQUAD_START = (173, 727)
    SWIPE_SQUAD_END = (173, 227)

    # Лист 2 (для плиток — слабые отряды)
    COORD_SHEET_2 = (384, 257)

    # ==================== ПУБЛИЧНЫЕ МЕТОДЫ ====================

    def send_squad_to_tile(
        self,
        emulator: Dict,
        resource: str,
        level_min: int,
        level_max: int,
        squad_key: str,
    ) -> bool:
        """
        Полный цикл отправки одного отряда на плитку

        Предусловие: бот на карте мира (видит лупу)

        Алгоритм:
        1. Клик по лупе → окно поиска
        2. Переход на вкладку ресурсов
        3. Сброс ресурсов в стартовую позицию (3 свайпа)
        4. Выбор нужного ресурса
        5. Сброс уровня (17× минус) → набор нужного уровня
        6. Поиск плитки (с повышением уровня до level_max)
        7. Клик "Собирать" → проверка "Походный Отряд"
        8. Выбор отряда → клик "Отправить"

        Args:
            emulator: словарь эмулятора
            resource: ключ ресурса ('apples', 'leaves', 'soil', 'sand')
            level_min: мин. уровень плитки
            level_max: макс. уровень плитки
            squad_key: ключ отряда ('special', 'squad_1', 'squad_2', 'squad_3')

        Returns:
            True — отряд успешно отправлен
            False — не удалось отправить (плитка не найдена, ошибка навигации)
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        res_name = RESOURCE_NAMES_RU.get(resource, resource)
        squad_name = SQUAD_NAMES_RU.get(squad_key, squad_key)

        logger.info(
            f"[{emu_name}] 🗺 Плитки: отправка {squad_name} "
            f"на {res_name} (ур. {level_min}-{level_max})"
        )

        for retry in range(self.MAX_SEARCH_RETRIES):
            if retry > 0:
                logger.info(
                    f"[{emu_name}] 🔄 Повтор отправки на плитку "
                    f"(попытка {retry + 1}/{self.MAX_SEARCH_RETRIES})"
                )

            # === ШАГ 1: Клик по лупе ===
            if not self._click_magnifier(emulator):
                continue

            # === ШАГ 2: Вкладка ресурсов ===
            tap(emulator, *self.COORD_RESOURCE_TAB)
            time.sleep(1)

            # === ШАГ 3: Сброс в стартовую позицию ===
            self._reset_resource_position(emulator)

            # === ШАГ 4: Выбор ресурса ===
            if not self._select_resource(emulator, resource):
                self._escape_search_window(emulator)
                continue

            # === ШАГ 5: Сброс и выбор уровня ===
            self._reset_level(emulator)
            self._set_level(emulator, level_min)

            # === ШАГ 6: Поиск плитки (от level_min до level_max) ===
            found_level = self._search_tile(emulator, level_min, level_max)
            if found_level is None:
                logger.warning(
                    f"[{emu_name}] ⚠️ Плитка {res_name} "
                    f"ур. {level_min}-{level_max} не найдена"
                )
                self._escape_search_window(emulator)
                return False  # Нет смысла повторять — плиток нет рядом

            logger.debug(
                f"[{emu_name}] ✅ Плитка {res_name} ур. {found_level} найдена"
            )

            # === ШАГ 7: "Собирать" → "Походный Отряд" ===
            if not self._click_collect_and_verify(emulator):
                self._escape_search_window(emulator)
                continue

            # === ШАГ 8: Выбор отряда и отправка ===
            if not self._select_squad_and_send(emulator, squad_key):
                self._escape_search_window(emulator)
                continue

            logger.success(
                f"[{emu_name}] ✅ {squad_name} отправлен на "
                f"{res_name} (ур. {found_level})"
            )
            return True

        logger.error(
            f"[{emu_name}] ❌ Не удалось отправить {squad_name} на {res_name} "
            f"за {self.MAX_SEARCH_RETRIES} попыток"
        )
        return False

    def setup_sheet_2(self, emulator: Dict) -> bool:
        """
        Переключить на Лист 2 (слабые отряды для фарма плиток)

        Аналогично WildsNavigation.setup_formation_sheet(), но:
        - Координата: (384, 257) вместо (325, 256)
        - Шаблон: sheet_2_icon вместо sheet_1_icon

        Предусловие: бот на карте мира (видит лупу)

        Returns:
            True — лист настроен
            False — критическая ошибка
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        logger.info(f"[{emu_name}] 📋 Настройка Листа 2 (плитки)...")

        for attempt in range(1, self.MAX_SHEET_ATTEMPTS + 1):
            # Шаг 1: Клик на иконку мечей
            swords = find_image(
                emulator, self.TEMPLATES['swords_icon'],
                threshold=self.THRESHOLD_TEMPLATE
            )
            if not swords:
                logger.warning(
                    f"[{emu_name}] ⚠️ Иконка мечей не найдена "
                    f"(попытка {attempt})"
                )
                press_key(emulator, "ESC")
                time.sleep(1)
                continue

            tap(emulator, swords[0], swords[1])
            time.sleep(2)

            # Шаг 2: Проверить заголовок "Походный Отряд"
            title = find_image(
                emulator, self.TEMPLATES['march_squad_title'],
                threshold=self.THRESHOLD_TEMPLATE
            )
            if not title:
                logger.warning(
                    f"[{emu_name}] ⚠️ Заголовок 'Походный Отряд' не найден"
                )
                press_key(emulator, "ESC")
                time.sleep(1)
                continue

            # Шаг 3: Клик по Листу 2
            tap(emulator, *self.COORD_SHEET_2)
            time.sleep(1)

            # Шаг 4: Проверить иконку Листа 2
            sheet_icon = find_image(
                emulator, self.TEMPLATES['sheet_2_icon'],
                threshold=self.THRESHOLD_TEMPLATE
            )
            if not sheet_icon:
                logger.warning(
                    f"[{emu_name}] ⚠️ Иконка Листа 2 не найдена, "
                    f"повторный клик..."
                )
                tap(emulator, *self.COORD_SHEET_2)
                time.sleep(1)
                sheet_icon = find_image(
                    emulator, self.TEMPLATES['sheet_2_icon'],
                    threshold=self.THRESHOLD_TEMPLATE
                )
                if not sheet_icon:
                    logger.error(
                        f"[{emu_name}] ❌ Не удалось переключить на Лист 2"
                    )
                    press_key(emulator, "ESC")
                    time.sleep(1)
                    continue

            # Шаг 5: Проверить "Сменить Состав" или "Пополнение Зверей"
            change_btn = find_image(
                emulator, self.TEMPLATES['change_squad_btn'],
                threshold=self.THRESHOLD_TEMPLATE
            )
            if change_btn:
                # Нужно сменить состав
                tap(emulator, change_btn[0], change_btn[1])
                time.sleep(1.5)

                # Кликаем "Подтвердить"
                confirm = find_image(
                    emulator, self.TEMPLATES['btn_confirm'],
                    threshold=self.THRESHOLD_TEMPLATE
                )
                if confirm:
                    tap(emulator, confirm[0], confirm[1])
                    time.sleep(1)

                press_key(emulator, "ESC")
                time.sleep(1)

                if self._is_on_world_map(emulator):
                    logger.success(
                        f"[{emu_name}] ✅ Лист 2 настроен (состав сменён)"
                    )
                    return True
                continue

            refill_btn = find_image(
                emulator, self.TEMPLATES['refill_beasts_btn'],
                threshold=self.THRESHOLD_TEMPLATE
            )
            if refill_btn:
                # Лист уже верный
                logger.info(
                    f"[{emu_name}] ✅ Лист 2 уже верный "
                    f"(видна кнопка Пополнение Зверей)"
                )
                press_key(emulator, "ESC")
                time.sleep(1)
                if self._is_on_world_map(emulator):
                    return True
                press_key(emulator, "ESC")
                time.sleep(1)
                return self._is_on_world_map(emulator)

            # Ни одна кнопка не найдена
            logger.error(
                f"[{emu_name}] ❌ Не найдены кнопки управления листом"
            )
            press_key(emulator, "ESC")
            time.sleep(1)

        logger.error(f"[{emu_name}] ❌ Не удалось настроить Лист 2")
        return False

    # ==================== ПРИВАТНЫЕ МЕТОДЫ ====================

    def _is_on_world_map(self, emulator: Dict) -> bool:
        """Проверить видна ли лупа (маркер карты мира)"""
        result = find_image(
            emulator, self.TEMPLATES['magnifying_glass'],
            threshold=self.THRESHOLD_MAGNIFIER
        )
        return result is not None

    def _click_magnifier(self, emulator: Dict) -> bool:
        """
        Найти лупу на карте мира и кликнуть по ней

        Returns:
            True — лупа найдена и кликнута, окно поиска открылось
            False — лупа не найдена
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        result = find_image(
            emulator, self.TEMPLATES['magnifying_glass'],
            threshold=self.THRESHOLD_MAGNIFIER
        )
        if not result:
            logger.warning(f"[{emu_name}] ⚠️ Лупа не найдена на карте мира")
            return False

        tap(emulator, result[0], result[1])
        time.sleep(1.5)
        return True

    def _reset_resource_position(self, emulator: Dict):
        """Сбросить позицию ресурсов в стартовую точку (3 свайпа вправо)"""
        for _ in range(self.SWIPE_RESET_COUNT):
            swipe(
                emulator,
                self.SWIPE_RESET_START[0], self.SWIPE_RESET_START[1],
                self.SWIPE_RESET_END[0], self.SWIPE_RESET_END[1],
                duration=300
            )
            time.sleep(0.3)
        time.sleep(0.5)

    def _select_resource(self, emulator: Dict, resource: str) -> bool:
        """
        Выбрать нужный ресурс в окне поиска плиток

        Предусловие: позиция ресурсов сброшена в стартовую

        Args:
            resource: 'apples', 'leaves', 'soil', 'sand'

        Returns:
            True — ресурс выбран
            False — неизвестный ресурс
        """
        config = self.RESOURCE_COORDS.get(resource)
        if not config:
            logger.error(f"Неизвестный ресурс для плиток: {resource}")
            return False

        # Свайпы (для грунта и песка)
        for _ in range(config['swipes_needed']):
            swipe(
                emulator,
                self.SWIPE_RESOURCE_START[0], self.SWIPE_RESOURCE_START[1],
                self.SWIPE_RESOURCE_END[0], self.SWIPE_RESOURCE_END[1],
                duration=800
            )
            time.sleep(1.5)  # 1 сек delay чтобы свайп засчитался

        # Клик по ресурсу
        tap(emulator, *config['coord'])
        time.sleep(0.5)
        return True

    def _reset_level(self, emulator: Dict):
        """Сбросить уровень плитки до 1 (17 кликов по минусу)"""
        for _ in range(self.LEVEL_RESET_CLICKS):
            tap(emulator, *self.COORD_LEVEL_MINUS)
            time.sleep(0.05)
        time.sleep(0.3)

    def _set_level(self, emulator: Dict, target_level: int):
        """
        Набрать нужный уровень плитки (кликами по плюсу)

        Предусловие: уровень сброшен до 1

        Args:
            target_level: нужный уровень (1-18)
        """
        clicks = target_level - 1
        for _ in range(clicks):
            tap(emulator, *self.COORD_LEVEL_PLUS)
            time.sleep(0.05)
        time.sleep(0.3)

    def _search_tile(
        self,
        emulator: Dict,
        level_min: int,
        level_max: int
    ) -> Optional[int]:
        """
        Поиск плитки с повышением уровня если не найдена

        Алгоритм:
        1. Клик "Поиск"
        2. Delay 2с
        3. Проверить шаблон "Поиск":
           - Видим → плитки нет рядом → level++ → плюс → снова "Поиск"
           - Не видим → плитка найдена!
        4. Если level > level_max → None (не найдена)

        Args:
            level_min: мин. уровень (уже установлен)
            level_max: макс. уровень

        Returns:
            int — уровень найденной плитки
            None — плитка не найдена в диапазоне
        """
        current_level = level_min

        while current_level <= level_max:
            # Клик "Поиск"
            tap(emulator, *self.COORD_SEARCH)
            time.sleep(2)  # Delay для прогрузки

            # Проверить: остались ли мы в окне поиска?
            search_btn = find_image(
                emulator, self.TEMPLATES['search_button'],
                threshold=self.THRESHOLD_TEMPLATE
            )

            if not search_btn:
                # Кнопка "Поиск" не видна → плитка найдена!
                return current_level

            # Плитка не найдена на текущем уровне
            logger.debug(
                f"Плитка ур. {current_level} не найдена, повышаю уровень..."
            )
            current_level += 1

            if current_level <= level_max:
                # Одно нажатие + чтобы повысить на 1 уровень
                tap(emulator, *self.COORD_LEVEL_PLUS)
                time.sleep(0.3)

        # Ни один уровень не подошёл
        return None

    def _click_collect_and_verify(self, emulator: Dict) -> bool:
        """
        Кликнуть "Собирать" и проверить заголовок "Походный Отряд"

        Returns:
            True — окно "Походный Отряд" открылось
            False — не удалось открыть
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        tap(emulator, *self.COORD_COLLECT)
        time.sleep(2)

        # Проверить заголовок "Походный Отряд"
        title = find_image(
            emulator, self.TEMPLATES['march_squad_title'],
            threshold=self.THRESHOLD_TEMPLATE
        )
        if title:
            return True

        # Не нашли — повторная попытка
        logger.warning(
            f"[{emu_name}] ⚠️ 'Походный Отряд' не найден после 'Собирать', "
            f"повторяю..."
        )
        tap(emulator, *self.COORD_COLLECT)
        time.sleep(2)

        title = find_image(
            emulator, self.TEMPLATES['march_squad_title'],
            threshold=self.THRESHOLD_TEMPLATE
        )
        if title:
            return True

        logger.error(
            f"[{emu_name}] ❌ Не удалось открыть 'Походный Отряд'"
        )
        return False

    def _select_squad_and_send(self, emulator: Dict, squad_key: str) -> bool:
        """
        Выбрать отряд и нажать "Отправить"

        Предусловие: окно "Походный Отряд" открыто

        Args:
            squad_key: 'special', 'squad_1', 'squad_2', 'squad_3'

        Returns:
            True — отряд выбран и отправлен
            False — не удалось
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        config = self.SQUAD_COORDS.get(squad_key)

        if not config:
            logger.error(f"[{emu_name}] Неизвестный отряд: {squad_key}")
            return False

        # Свайп если нужен (для squad_2, squad_3)
        if config['needs_swipe']:
            swipe(
                emulator,
                self.SWIPE_SQUAD_START[0], self.SWIPE_SQUAD_START[1],
                self.SWIPE_SQUAD_END[0], self.SWIPE_SQUAD_END[1],
                duration=400
            )
            time.sleep(1)

        # Клик по отряду
        tap(emulator, *config['coord'])
        time.sleep(0.5)

        # Клик "Отправить"
        tap(emulator, *self.COORD_SEND)
        time.sleep(1.5)

        # После "Отправить" окно должно закрыться автоматически
        # Проверяем: видим ли лупу (вернулись на карту мира)?
        if self._is_on_world_map(emulator):
            return True

        # Иногда нужно подождать дольше
        time.sleep(1)
        if self._is_on_world_map(emulator):
            return True

        logger.warning(
            f"[{emu_name}] ⚠️ После 'Отправить' лупа не найдена, "
            f"пробую ESC..."
        )
        press_key(emulator, "ESC")
        time.sleep(1)

        return self._is_on_world_map(emulator)

    def _escape_search_window(self, emulator: Dict):
        """Выйти из окна поиска плиток (ESC пока не увидим лупу или 3 попытки)"""
        for _ in range(3):
            press_key(emulator, "ESC")
            time.sleep(1)
            if self._is_on_world_map(emulator):
                return