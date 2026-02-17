"""
Функция пополнения Зоны Кормления
Проверяет статус по иконке лапки и пополняет при необходимости

Механика:
- Иконка лапки в верхнем левом углу: зелёная = ОК, красная = пусто
- Навигация: Развитие → Зона кормления → клик по зданию
- Основной путь: иконка "Доставка" → кнопка "Доставка" → окно закрывается
- Альт. путь: "Восполнить ресурсы" → "Подтвердить" → окно закрывается
- ESC НЕ НУЖЕН — после пополнения бот на главном экране

Вызывается перед строительством для обеспечения достаточной популяции.

Версия: 1.0
Дата создания: 2025-02-17
"""

import os
import time
from typing import Optional

from functions.base_function import BaseFunction
from functions.building.navigation_panel import NavigationPanel
from utils.adb_controller import tap, press_key
from utils.image_recognition import find_image, detect_feeding_zone_status
from utils.logger import logger

# Базовая директория проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FeedingZoneFunction(BaseFunction):
    """
    Функция пополнения Зоны Кормления

    Проверяет иконку лапки на главном экране:
    - Зелёная обводка → ресурсы есть, пропускаем
    - Красная обводка → пусто, нужно пополнить
    """

    # Координаты центра здания после "Перейти"
    BUILDING_CENTER = (268, 517)

    # Шаблоны изображений
    TEMPLATES = {
        'delivery_icon': os.path.join(BASE_DIR, 'data', 'templates', 'feeding_zone', 'delivery_icon.png'),
        'delivery_button': os.path.join(BASE_DIR, 'data', 'templates', 'feeding_zone', 'delivery_button.png'),
        'replenish_button': os.path.join(BASE_DIR, 'data', 'templates', 'feeding_zone', 'replenish_button.png'),
        'confirm_button': os.path.join(BASE_DIR, 'data', 'templates', 'feeding_zone', 'confirm_button.png'),
    }

    # Пороги распознавания
    THRESHOLD_ICON = 0.8
    THRESHOLD_BUTTON = 0.85

    def __init__(self, emulator):
        """Инициализация функции пополнения Зоны Кормления"""
        super().__init__(emulator)
        self.name = "FeedingZoneFunction"
        self.panel = NavigationPanel()

        logger.info(f"[{self.emulator_name}] ✅ FeedingZoneFunction инициализирована")

    # ==================== can_execute / execute ====================

    def can_execute(self) -> bool:
        """
        Можно ли выполнить пополнение?

        Проверяем иконку лапки на главном экране:
        - 'empty' (красная) → True, нужно пополнить
        - 'ok' (зелёная) → False, ресурсы есть
        - None (не удалось определить) → True, на всякий случай проверим
        """
        status = detect_feeding_zone_status(self.emulator)

        if status == 'ok':
            logger.debug(f"[{self.emulator_name}] 🟢 Зона Кормления: ресурсы есть, пропускаем")
            return False
        elif status == 'empty':
            logger.info(f"[{self.emulator_name}] 🔴 Зона Кормления: пуста, нужно пополнить!")
            return True
        else:
            logger.warning(f"[{self.emulator_name}] ⚠️ Зона Кормления: не удалось определить статус, попробуем пополнить")
            return True

    def execute(self):
        """
        Пополнить Зону Кормления

        Алгоритм:
        1. Навигация к Зоне Кормления через панель (Развитие → Зона кормления)
        2. Клик по зданию (268, 517)
        3. Найти иконку "Доставка" → клик
        4. В окне: кнопка "Доставка" → клик → окно закрывается
        5. Альт: "Восполнить ресурсы" → клик → "Подтвердить" → клик
        6. Сброс nav_state
        """
        logger.info(f"[{self.emulator_name}] 🍎 Начинаю пополнение Зоны Кормления")

        # Шаг 1: Навигация к Зоне Кормления
        if not self._navigate_to_feeding_zone():
            logger.error(f"[{self.emulator_name}] ❌ Не удалось перейти к Зоне Кормления")
            self._reset_nav_state()
            return

        # Шаг 2: Пополнение
        success = self._refill_feeding_zone()

        if success:
            logger.success(f"[{self.emulator_name}] ✅ Зона Кормления пополнена!")
        else:
            logger.warning(f"[{self.emulator_name}] ⚠️ Не удалось пополнить Зону Кормления")

        # Шаг 3: Сброс nav_state
        self._reset_nav_state()

    # ==================== НАВИГАЦИЯ ====================

    def _navigate_to_feeding_zone(self) -> bool:
        """
        Навигация к Зоне Кормления через панель навигации
        Развитие → Зона кормления → Перейти

        Returns:
            bool: True если успешно перешли к зданию
        """
        logger.debug(f"[{self.emulator_name}] 📍 Навигация к Зоне Кормления")

        success = self.panel.navigate_to_building(
            self.emulator, "Зона кормления", building_index=1
        )

        if not success:
            logger.error(f"[{self.emulator_name}] ❌ NavigationPanel не смогла перейти к Зоне Кормления")
            return False

        return True

    # ==================== ПОПОЛНЕНИЕ ====================

    def _refill_feeding_zone(self) -> bool:
        """
        Пополнить Зону Кормления

        Алгоритм:
        1. Клик по зданию (268, 517) — появляются иконки вокруг
        2. Найти иконку "Доставка" → клик
        3. В открывшемся окне:
           a) Основной путь: кнопка "Доставка" → клик → окно закрывается
           b) Альт. путь: "Восполнить ресурсы" → клик → "Подтвердить" → клик
        4. ESC НЕ НУЖЕН — окно закрывается автоматически

        Returns:
            bool: True если пополнение успешно
        """
        # Шаг 1: Клик по зданию
        logger.debug(f"[{self.emulator_name}] 🖱️ Клик по зданию Зона Кормления")
        tap(self.emulator, x=self.BUILDING_CENTER[0], y=self.BUILDING_CENTER[1])
        time.sleep(1.5)

        # Шаг 2: Поиск и клик иконки "Доставка"
        delivery_icon_pos = self._find_template_with_retry(
            self.TEMPLATES['delivery_icon'],
            self.THRESHOLD_ICON,
            max_retries=3,
            retry_delay=0.5,
            description="Иконка Доставка"
        )

        if not delivery_icon_pos:
            logger.warning(f"[{self.emulator_name}] ⚠️ Иконка 'Доставка' не найдена")
            press_key(self.emulator, "ESC")
            time.sleep(0.5)
            return False

        logger.debug(f"[{self.emulator_name}] ✅ Иконка 'Доставка' найдена: {delivery_icon_pos}")
        tap(self.emulator, x=delivery_icon_pos[0], y=delivery_icon_pos[1])
        time.sleep(1.5)

        # Шаг 3: В окне — ищем кнопку "Доставка" (основной путь)
        delivery_btn_pos = self._find_template_with_retry(
            self.TEMPLATES['delivery_button'],
            self.THRESHOLD_BUTTON,
            max_retries=3,
            retry_delay=0.5,
            description="Кнопка Доставка"
        )

        if delivery_btn_pos:
            # Основной путь — кнопка "Доставка"
            logger.debug(f"[{self.emulator_name}] ✅ Кнопка 'Доставка' найдена: {delivery_btn_pos}")
            tap(self.emulator, x=delivery_btn_pos[0], y=delivery_btn_pos[1])
            time.sleep(1.0)  # Окно закрывается автоматически
            return True

        # Шаг 3 (альт): Ищем "Восполнить ресурсы"
        logger.info(f"[{self.emulator_name}] 🔄 Кнопка 'Доставка' не найдена, ищем 'Восполнить ресурсы'...")

        replenish_pos = self._find_template_with_retry(
            self.TEMPLATES['replenish_button'],
            self.THRESHOLD_BUTTON,
            max_retries=3,
            retry_delay=0.5,
            description="Восполнить ресурсы"
        )

        if not replenish_pos:
            logger.warning(f"[{self.emulator_name}] ⚠️ Ни 'Доставка', ни 'Восполнить ресурсы' не найдены")
            press_key(self.emulator, "ESC")
            time.sleep(0.5)
            return False

        # Клик "Восполнить ресурсы"
        logger.debug(f"[{self.emulator_name}] ✅ Кнопка 'Восполнить ресурсы' найдена: {replenish_pos}")
        tap(self.emulator, x=replenish_pos[0], y=replenish_pos[1])
        time.sleep(1.5)

        # Ищем "Подтвердить"
        confirm_pos = self._find_template_with_retry(
            self.TEMPLATES['confirm_button'],
            self.THRESHOLD_BUTTON,
            max_retries=3,
            retry_delay=0.5,
            description="Подтвердить"
        )

        if not confirm_pos:
            logger.warning(f"[{self.emulator_name}] ⚠️ Кнопка 'Подтвердить' не найдена")
            press_key(self.emulator, "ESC")
            time.sleep(0.5)
            return False

        # Клик "Подтвердить"
        logger.debug(f"[{self.emulator_name}] ✅ Кнопка 'Подтвердить' найдена: {confirm_pos}")
        tap(self.emulator, x=confirm_pos[0], y=confirm_pos[1])
        time.sleep(1.0)  # Окно закрывается автоматически

        return True

    # ==================== УТИЛИТЫ ====================

    def _find_template_with_retry(self, template_path: str, threshold: float,
                                   max_retries: int = 3, retry_delay: float = 0.5,
                                   description: str = "") -> Optional[tuple]:
        """
        Поиск шаблона с повторными попытками

        Args:
            template_path: путь к шаблону
            threshold: порог распознавания
            max_retries: максимум попыток
            retry_delay: задержка между попытками
            description: описание для логов

        Returns:
            (x, y) координаты центра или None
        """
        for attempt in range(1, max_retries + 1):
            result = find_image(self.emulator, template_path, threshold=threshold)

            if result:
                return result

            if attempt < max_retries:
                logger.debug(f"[{self.emulator_name}] 🔄 '{description}' не найдена, "
                             f"попытка {attempt}/{max_retries}")
                time.sleep(retry_delay)

        return None

    def _reset_nav_state(self):
        """Сброс состояния навигации после работы с Зоной Кормления"""
        logger.debug(f"[{self.emulator_name}] 🔄 Сброс nav_state после Зоны Кормления")
        self.panel.nav_state.is_panel_open = False
        self.panel.nav_state.current_tab = None
        self.panel.nav_state.current_section = None
        self.panel.nav_state.current_subsection = None
        self.panel.nav_state.is_collapsed = False
        self.panel.nav_state.is_scrolled_to_top = False