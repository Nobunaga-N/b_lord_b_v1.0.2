"""
Навигация для охоты на диких существ

Обеспечивает переходы:
- Поместье → Карта мира
- Карта мира → Окно автоохоты
- Окно автоохоты → Поместье
- Настройка листа формаций (Лист 1 / Лист 2)

Маркеры состояний:
- Внутри поместья: видна иконка панели навигации (navigation_icon)
- На карте мира: видна лупа (magnifying_glass)
- В окне автоохоты: виден заголовок "Автоохота на Диких Существ"

Версия: 1.0
Дата создания: 2025-03-11
"""

import os
import time
from typing import Dict, Optional
from utils.adb_controller import tap, press_key
from utils.image_recognition import find_image
from utils.recovery_manager import recovery_manager
from utils.logger import logger

# Базовая директория проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class WildsNavigation:
    """
    Навигация для охоты на диких существ

    Методы:
    - ensure_on_world_map()    — гарантировать что бот на карте мира
    - ensure_in_estate()       — гарантировать что бот в поместье
    - open_autohunt_window()   — открыть окно автоохоты (полный путь)
    - close_autohunt_window()  — закрыть окно автоохоты (ESC)
    - setup_formation_sheet()  — настройка листа формаций
    """

    # ==================== ШАБЛОНЫ ====================
    # Закинуть соответствующие PNG в data/templates/wilds/

    TEMPLATES = {
        # Кнопка выхода на карту мира (из поместья)
        'world_map_button': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'world_map_button.png'
        ),
        # Лупа — маркер карты мира
        'magnifying_glass': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'magnifying_glass.png'
        ),
        # Иконка панели навигации — маркер поместья
        'navigation_icon': os.path.join(
            BASE_DIR, 'data', 'templates', 'building', 'navigation_icon.png'
        ),
        # Иконка мечей (открывает "Походный Отряд")
        'swords_icon': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'swords_icon.png'
        ),
        # Заголовок "Походный Отряд"
        'march_squad_title': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'march_squad_title.png'
        ),
        # Иконка выбранного Листа 1
        'sheet_1_icon': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'sheet_1_icon.png'
        ),
        # Кнопка "Сменить Состав"
        'change_squad_btn': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'change_squad_btn.png'
        ),
        # Кнопка "Пополнение Зверей"
        'refill_beasts_btn': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'refill_beasts_btn.png'
        ),
        # Кнопка "Подтвердить" (общая для диалогов)
        'btn_confirm': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'btn_confirm.png'
        ),
        # Заголовок "Автоохота на Диких Существ"
        'autohunt_title': os.path.join(
            BASE_DIR, 'data', 'templates', 'wilds', 'autohunt_title.png'
        ),
    }

    # ==================== НАСТРОЙКИ ====================

    MAX_MAP_ATTEMPTS = 3        # Попытки найти карту мира
    MAX_MAGNIFIER_CHECKS = 5    # Попытки найти лупу после клика
    MAX_AUTOHUNT_ATTEMPTS = 3   # Попытки открыть окно автоохоты
    MAX_SHEET_ATTEMPTS = 2      # Попытки настроить лист формаций

    THRESHOLD_TEMPLATE = 0.8    # Порог для обычных шаблонов
    THRESHOLD_MAGNIFIER = 0.85  # Порог для лупы (уникальный элемент)
    THRESHOLD_NAV_ICON = 0.8    # Порог для иконки навигации

    # Координаты
    COORD_AUTOHUNT_BUTTON = (37, 556)   # Кнопка открытия автоохоты на карте
    COORD_SHEET_1 = (325, 256)          # Клик по Листу 1
    COORD_WORLD_MAP_ENTER = None        # Определяется по шаблону world_map_button

    # ==================== ПУБЛИЧНЫЕ МЕТОДЫ ====================

    def ensure_on_world_map(self, emulator: Dict) -> bool:
        """
        Гарантировать что бот находится на карте мира (видит лупу)

        Алгоритм:
        1. Проверить лупу → если есть, уже на карте
        2. Найти кнопку карты мира → кликнуть → проверить лупу
        3. Если не получилось → ESC-ресет → повтор
        4. Если и это не помогло → return False (вызывающий код решает что делать)

        Returns:
            bool: True если бот на карте мира
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Быстрая проверка — уже на карте?
        if self._is_on_world_map(emulator):
            logger.debug(f"[{emu_name}] ✅ Уже на карте мира")
            return True

        for attempt in range(1, self.MAX_MAP_ATTEMPTS + 1):
            logger.info(
                f"[{emu_name}] 🗺️ Выход на карту мира "
                f"(попытка {attempt}/{self.MAX_MAP_ATTEMPTS})"
            )

            # Попытка 1: найти кнопку карты и кликнуть
            if self._click_world_map_button(emulator):
                if self._wait_for_magnifier(emulator):
                    logger.success(f"[{emu_name}] ✅ Успешно вышли на карту мира")
                    return True

            # Не получилось — ESC-ресет для очистки UI
            logger.warning(
                f"[{emu_name}] ⚠️ Карта мира не найдена, "
                f"выполняю ESC-ресет..."
            )
            recovery_manager.clear_ui_state(emulator)
            time.sleep(1)

            # После ресета снова ищем кнопку карты
            if self._click_world_map_button(emulator):
                if self._wait_for_magnifier(emulator):
                    logger.success(
                        f"[{emu_name}] ✅ Вышли на карту мира "
                        f"после ESC-ресета"
                    )
                    return True

        logger.error(
            f"[{emu_name}] ❌ Не удалось выйти на карту мира "
            f"за {self.MAX_MAP_ATTEMPTS} попыток"
        )
        return False

    def ensure_in_estate(self, emulator: Dict) -> bool:
        """
        Гарантировать что бот внутри поместья (видит navigation_icon)

        Алгоритм:
        1. Проверить navigation_icon → если есть, уже в поместье
        2. Проверить лупу → если есть, мы на карте → кликнуть карту мира
        3. ESC-ресет → повтор

        Returns:
            bool: True если бот в поместье
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Быстрая проверка — уже в поместье?
        if self._is_in_estate(emulator):
            logger.debug(f"[{emu_name}] ✅ Уже в поместье")
            return True

        for attempt in range(1, 4):
            logger.info(
                f"[{emu_name}] 🏠 Возврат в поместье "
                f"(попытка {attempt}/3)"
            )

            # Проверяем: может мы на карте мира?
            if self._is_on_world_map(emulator):
                # На карте мира — кликаем кнопку карты для входа в город
                logger.debug(f"[{emu_name}] На карте мира, входим в поместье...")
                if self._click_world_map_button(emulator):
                    time.sleep(2)
                    if self._is_in_estate(emulator):
                        logger.success(f"[{emu_name}] ✅ Вернулись в поместье")
                        return True

                    # Может снова видим лупу — кликнули мимо
                    if self._is_on_world_map(emulator):
                        # Ещё раз
                        self._click_world_map_button(emulator)
                        time.sleep(2)
                        if self._is_in_estate(emulator):
                            logger.success(f"[{emu_name}] ✅ Вернулись в поместье")
                            return True

            # Возможно мы внутри какого-то окна — ESC-ресет
            logger.debug(f"[{emu_name}] ESC-ресет для возврата в поместье...")
            recovery_manager.clear_ui_state(emulator)
            time.sleep(1)

            if self._is_in_estate(emulator):
                logger.success(f"[{emu_name}] ✅ Вернулись в поместье после ресета")
                return True

        logger.error(f"[{emu_name}] ❌ Не удалось вернуться в поместье")
        return False

    def open_autohunt_window(self, emulator: Dict) -> bool:
        """
        Открыть окно автоохоты на диких существ (полный путь)

        Алгоритм:
        1. ensure_on_world_map()
        2. Клик по (37, 556)
        3. Проверить заголовок "Автоохота на Диких Существ"
        4. Если не найден → повтор (лупа → клик)

        Returns:
            bool: True если окно автоохоты открыто
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Шаг 1: Убедиться что мы на карте мира
        if not self.ensure_on_world_map(emulator):
            return False

        # Шаг 2: Открыть окно автоохоты
        for attempt in range(1, self.MAX_AUTOHUNT_ATTEMPTS + 1):
            logger.info(
                f"[{emu_name}] 🐻 Открытие окна автоохоты "
                f"(попытка {attempt}/{self.MAX_AUTOHUNT_ATTEMPTS})"
            )

            tap(emulator, *self.COORD_AUTOHUNT_BUTTON)
            time.sleep(2)

            # Проверяем заголовок
            if self._is_autohunt_window_open(emulator):
                logger.success(f"[{emu_name}] ✅ Окно автоохоты открыто")
                return True

            # Не открылось — проверяем лупу
            logger.warning(
                f"[{emu_name}] ⚠️ Окно автоохоты не открылось, "
                f"проверяю карту мира..."
            )

            if not self._is_on_world_map(emulator):
                # Мы не на карте — пробуем вернуться
                if not self.ensure_on_world_map(emulator):
                    return False

        logger.error(
            f"[{emu_name}] ❌ Не удалось открыть окно автоохоты "
            f"за {self.MAX_AUTOHUNT_ATTEMPTS} попыток"
        )
        return False

    def close_autohunt_window(self, emulator: Dict) -> bool:
        """
        Закрыть окно автоохоты (ESC)

        Returns:
            bool: True если окно закрыто (видим лупу)
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        press_key(emulator, "ESC")
        time.sleep(1)

        if self._is_on_world_map(emulator):
            logger.debug(f"[{emu_name}] ✅ Окно автоохоты закрыто")
            return True

        # Ещё раз ESC на всякий случай
        press_key(emulator, "ESC")
        time.sleep(1)

        if self._is_on_world_map(emulator):
            return True

        logger.warning(f"[{emu_name}] ⚠️ После закрытия автоохоты лупа не найдена")
        return False

    def setup_formation_sheet(self, emulator: Dict) -> bool:
        """
        Настройка листа формаций (переключение на Лист 1)

        Вызывать ТОЛЬКО если use_sheet_2=True и Лорд >= 16

        Предусловие: бот на карте мира (видит лупу)

        Алгоритм:
        1. Клик на иконку мечей
        2. Проверить заголовок "Походный Отряд"
        3. Клик по Листу 1 (325, 256)
        4. Проверить иконку Листа 1
        5. Если "Сменить Состав" → кликнуть → "Подтвердить" → ESC
        6. Если "Пополнение Зверей" → лист верный → ESC
        7. Проверить лупу

        Returns:
            bool: True если лист настроен (или не нужен)
            False: критическая ошибка → вызывающий код заморозит функцию
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emu_name}] 📋 Настройка листа формаций...")

        for attempt in range(1, self.MAX_SHEET_ATTEMPTS + 1):
            # Шаг 1: Клик на мечи
            swords = find_image(
                emulator, self.TEMPLATES['swords_icon'],
                threshold=self.THRESHOLD_TEMPLATE
            )
            if not swords:
                logger.warning(
                    f"[{emu_name}] ⚠️ Иконка мечей не найдена "
                    f"(попытка {attempt})"
                )
                # Проверяем лупу — может окно перекрывает
                if not self._is_on_world_map(emulator):
                    recovery_manager.clear_ui_state(emulator)
                    time.sleep(1)
                    if not self.ensure_on_world_map(emulator):
                        return False
                continue

            tap(emulator, swords[0], swords[1])
            time.sleep(2)

            # Шаг 2: Проверяем заголовок "Походный Отряд"
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

            # Шаг 3: Клик по Листу 1
            tap(emulator, *self.COORD_SHEET_1)
            time.sleep(1)

            # Шаг 4: Проверить иконку Листа 1
            sheet_icon = find_image(
                emulator, self.TEMPLATES['sheet_1_icon'],
                threshold=self.THRESHOLD_TEMPLATE
            )
            if not sheet_icon:
                logger.warning(
                    f"[{emu_name}] ⚠️ Иконка Листа 1 не найдена, "
                    f"повторный клик..."
                )
                tap(emulator, *self.COORD_SHEET_1)
                time.sleep(1)
                sheet_icon = find_image(
                    emulator, self.TEMPLATES['sheet_1_icon'],
                    threshold=self.THRESHOLD_TEMPLATE
                )
                if not sheet_icon:
                    logger.error(
                        f"[{emu_name}] ❌ Не удалось выбрать Лист 1"
                    )
                    press_key(emulator, "ESC")
                    time.sleep(1)
                    return False

            # Шаг 5: Проверяем "Сменить Состав" или "Пополнение Зверей"
            change_btn = find_image(
                emulator, self.TEMPLATES['change_squad_btn'],
                threshold=self.THRESHOLD_TEMPLATE
            )

            if change_btn:
                # Нужно сменить состав
                logger.info(f"[{emu_name}] 🔄 Смена состава формации...")
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

                # ESC для выхода из окна
                press_key(emulator, "ESC")
                time.sleep(1)

                # Проверяем лупу
                if self._is_on_world_map(emulator):
                    logger.success(
                        f"[{emu_name}] ✅ Лист формаций настроен "
                        f"(состав сменён)"
                    )
                    return True

                logger.warning(
                    f"[{emu_name}] ⚠️ Лупа не найдена после смены состава"
                )
                continue

            # Проверяем "Пополнение Зверей" (лист уже верный)
            refill_btn = find_image(
                emulator, self.TEMPLATES['refill_beasts_btn'],
                threshold=self.THRESHOLD_TEMPLATE
            )

            if refill_btn:
                logger.info(
                    f"[{emu_name}] ✅ Лист формаций уже верный "
                    f"(видна кнопка Пополнение Зверей)"
                )
                press_key(emulator, "ESC")
                time.sleep(1)

                if self._is_on_world_map(emulator):
                    return True

                # Ещё ESC
                press_key(emulator, "ESC")
                time.sleep(1)
                return self._is_on_world_map(emulator)

            # Ни "Сменить Состав", ни "Пополнение Зверей" не найдены
            logger.error(
                f"[{emu_name}] ❌ Не найдены кнопки управления листом"
            )
            press_key(emulator, "ESC")
            time.sleep(1)

        # Все попытки исчерпаны
        logger.error(
            f"[{emu_name}] ❌ Не удалось настроить лист формаций"
        )
        return False

    # ==================== ПРИВАТНЫЕ МЕТОДЫ ====================

    def _is_on_world_map(self, emulator: Dict) -> bool:
        """Проверить видна ли лупа (маркер карты мира)"""
        result = find_image(
            emulator, self.TEMPLATES['magnifying_glass'],
            threshold=self.THRESHOLD_MAGNIFIER
        )
        return result is not None

    def _is_in_estate(self, emulator: Dict) -> bool:
        """Проверить видна ли иконка навигации (маркер поместья)"""
        result = find_image(
            emulator, self.TEMPLATES['navigation_icon'],
            threshold=self.THRESHOLD_NAV_ICON
        )
        return result is not None

    def _is_autohunt_window_open(self, emulator: Dict) -> bool:
        """Проверить виден ли заголовок окна автоохоты"""
        result = find_image(
            emulator, self.TEMPLATES['autohunt_title'],
            threshold=self.THRESHOLD_TEMPLATE
        )
        return result is not None

    def _click_world_map_button(self, emulator: Dict) -> bool:
        """
        Найти и кликнуть кнопку карты мира

        Returns:
            bool: True если кнопка найдена и кликнута
        """
        result = find_image(
            emulator, self.TEMPLATES['world_map_button'],
            threshold=self.THRESHOLD_TEMPLATE
        )
        if result:
            tap(emulator, result[0], result[1])
            time.sleep(2)
            return True

        logger.debug(
            f"[{emulator.get('name', '?')}] "
            f"Кнопка карты мира не найдена"
        )
        return False

    def _wait_for_magnifier(self, emulator: Dict) -> bool:
        """
        Ждать появления лупы (несколько попыток с паузами)

        Returns:
            bool: True если лупа найдена
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        for check in range(1, self.MAX_MAGNIFIER_CHECKS + 1):
            if self._is_on_world_map(emulator):
                return True

            logger.debug(
                f"[{emu_name}] Лупа не найдена "
                f"({check}/{self.MAX_MAGNIFIER_CHECKS}), жду 2с..."
            )
            time.sleep(2)

        return False