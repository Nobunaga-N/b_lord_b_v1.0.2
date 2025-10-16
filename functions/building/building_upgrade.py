"""
Модуль улучшения зданий
Обрабатывает весь процесс улучшения здания от клика до записи в БД

Версия: 1.0
Дата создания: 2025-01-17
"""

import os
import time
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from utils.adb_controller import tap, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BuildingUpgrade:
    """
    Класс для улучшения зданий

    Процесс:
    1. Клик по зданию (после navigate_to_building)
    2. Поиск и клик "Улучшить"
    3. Обработка окна улучшения (ресурсы/пополнение/нехватка)
    4. Парсинг таймера через "Ускорить"
    5. Обработка быстрого завершения
    6. Обновление БД
    """

    # Координаты
    BUILDING_CENTER = (268, 517)  # Центр здания после "Перейти"

    # Область парсинга таймера (x1, y1, x2, y2)
    TIMER_AREA = (213, 67, 335, 106)

    # Шаблоны изображений
    TEMPLATES = {
        # Иконки действий
        'upgrade_icon': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'upgrade_icon.png'),
        'speedup_icon': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'speedup_icon.png'),

        # Кнопки
        'button_upgrade': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'button_upgrade.png'),
        'button_refill': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'button_refill.png'),
        'button_confirm': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'button_confirm.png'),

        # Окна
        'window_refill': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'window_refill.png'),
        'window_no_resources': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'window_no_resources.png'),
    }

    # Пороги для поиска изображений
    THRESHOLD_ICON = 0.7  # Для иконок (могут быть разных размеров)
    THRESHOLD_BUTTON = 0.85  # Для кнопок
    THRESHOLD_WINDOW = 0.85  # Для заголовков окон

    def __init__(self):
        """Инициализация модуля улучшения"""
        self.ocr = OCREngine()

        # Проверяем шаблоны
        for name, path in self.TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "❌"
            logger.debug(f"{status} Шаблон '{name}': {path}")

        logger.info("✅ BuildingUpgrade инициализирован")

    def upgrade_building(self, emulator: Dict, building_name: str,
                        building_index: Optional[int] = None) -> Tuple[bool, Optional[int]]:
        """
        ГЛАВНЫЙ МЕТОД - Улучшить здание

        Предусловие: бот уже перешел к зданию через navigate_to_building()

        Args:
            emulator: объект эмулятора
            building_name: название здания
            building_index: индекс (для множественных зданий)

        Returns:
            (успех, таймер_в_секундах)
            - (True, 3600) - улучшение началось, таймер 1 час
            - (True, 0) - улучшение завершилось мгновенно (помощь альянса)
            - (False, None) - нехватка ресурсов, нужна заморозка
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        building_display = f"{building_name}"
        if building_index is not None:
            building_display += f" #{building_index}"

        logger.info(f"[{emulator_name}] 🔨 Начало улучшения: {building_display}")

        # ШАГ 1: Клик по зданию
        if not self._click_building(emulator):
            return False, None

        # ШАГ 2: Поиск и клик "Улучшить"
        if not self._click_upgrade_icon(emulator):
            return False, None

        # ШАГ 3: Обработка окна улучшения
        upgrade_result = self._handle_upgrade_window(emulator)

        if upgrade_result == "no_resources":
            # Нехватка ресурсов - нужна заморозка
            logger.warning(f"[{emulator_name}] ❌ Недостаточно ресурсов для {building_display}")
            return False, None

        elif upgrade_result == "started":
            # Улучшение началось
            logger.success(f"[{emulator_name}] ✅ Улучшение началось: {building_display}")

            # ШАГ 4: Парсинг таймера
            timer_seconds = self._parse_upgrade_timer(emulator)

            if timer_seconds is None:
                # Таймер не найден - возможно быстрое завершение
                logger.info(f"[{emulator_name}] 🚀 Возможно быстрое завершение (помощь альянса)")
                return True, 0

            logger.info(f"[{emulator_name}] ⏱️ Таймер улучшения: {self._format_time(timer_seconds)}")
            return True, timer_seconds

        else:
            # Неизвестная ошибка
            logger.error(f"[{emulator_name}] ❌ Неизвестная ошибка при улучшении")
            return False, None

    def _click_building(self, emulator: Dict) -> bool:
        """Кликнуть по зданию в центре экрана"""
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Клик по зданию ({self.BUILDING_CENTER[0]}, {self.BUILDING_CENTER[1]})")
        tap(emulator, x=self.BUILDING_CENTER[0], y=self.BUILDING_CENTER[1])
        time.sleep(1.5)  # Ждем появления иконок

        return True

    def _click_upgrade_icon(self, emulator: Dict) -> bool:
        """
        Найти и кликнуть иконку "Улучшить"

        Иконка - стрелка вверх, размер может быть разным для разных зданий
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Поиск иконки 'Улучшить'...")

        # Попытка найти иконку (несколько попыток т.к. иконка может быть разных размеров)
        for attempt in range(3):
            result = find_image(emulator, self.TEMPLATES['upgrade_icon'],
                              threshold=self.THRESHOLD_ICON)

            if result:
                # find_image возвращает (x, y) координаты центра
                center_x, center_y = result

                logger.debug(f"[{emulator_name}] Найдена иконка 'Улучшить' на ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)  # Ждем открытия окна
                return True

            time.sleep(0.5)

        logger.error(f"[{emulator_name}] ❌ Иконка 'Улучшить' не найдена")
        return False

    def _handle_upgrade_window(self, emulator: Dict) -> str:
        """
        Обработать окно улучшения

        Возможные сценарии:
        1. Кнопка "Улучшение" - ресурсов хватает
        2. Кнопка "Пополнить ресурсы одним кликом" - автопополнение
           2а. Окно "Пополнить ресурсы" - успешно
           2б. Окно "Недостаточно ресурсов" - провал

        Returns:
            "started" - улучшение началось
            "no_resources" - нехватка ресурсов
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ПРОВЕРКА 1: Кнопка "Улучшение"
        if find_image(emulator, self.TEMPLATES['button_upgrade'],
                     threshold=self.THRESHOLD_BUTTON):
            logger.debug(f"[{emulator_name}] Найдена кнопка 'Улучшение'")

            # Клик по кнопке
            result = find_image(emulator, self.TEMPLATES['button_upgrade'],
                              threshold=self.THRESHOLD_BUTTON)
            if result:
                center_x, center_y = result
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)
                return "started"

        # ПРОВЕРКА 2: Кнопка "Пополнить ресурсы одним кликом"
        if find_image(emulator, self.TEMPLATES['button_refill'],
                     threshold=self.THRESHOLD_BUTTON):
            logger.debug(f"[{emulator_name}] Найдена кнопка 'Пополнить ресурсы'")

            # Клик по кнопке
            result = find_image(emulator, self.TEMPLATES['button_refill'],
                              threshold=self.THRESHOLD_BUTTON)
            if result:
                center_x, center_y = result
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)

            # Проверяем какое окно открылось
            return self._handle_refill_window(emulator)

        logger.warning(f"[{emulator_name}] ⚠️ Не найдена кнопка улучшения")
        return "error"

    def _handle_refill_window(self, emulator: Dict) -> str:
        """
        Обработать окно после клика "Пополнить ресурсы"

        2 варианта:
        - Окно "Пополнить ресурсы одним кликом" - успех
        - Окно "Недостаточно ресурсов" - провал

        Returns:
            "started" - ресурсы пополнены, постройка началась
            "no_resources" - недостаточно ресурсов
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ВАРИАНТ 1: Окно "Пополнить ресурсы одним кликом"
        if find_image(emulator, self.TEMPLATES['window_refill'],
                     threshold=self.THRESHOLD_WINDOW):
            logger.debug(f"[{emulator_name}] Окно 'Пополнить ресурсы' - подтверждаем")

            # Ищем и кликаем кнопку "Подтвердить"
            result = find_image(emulator, self.TEMPLATES['button_confirm'],
                              threshold=self.THRESHOLD_BUTTON)
            if result:
                center_x, center_y = result
                tap(emulator, x=center_x, y=center_y)
                time.sleep(2)
                return "started"

        # ВАРИАНТ 2: Окно "Недостаточно ресурсов"
        if find_image(emulator, self.TEMPLATES['window_no_resources'],
                     threshold=self.THRESHOLD_WINDOW):
            logger.warning(f"[{emulator_name}] ⚠️ Окно 'Недостаточно ресурсов'")

            # 2x ESC для закрытия
            press_key(emulator, "ESC")
            time.sleep(0.5)
            press_key(emulator, "ESC")
            time.sleep(0.5)

            return "no_resources"

        logger.warning(f"[{emulator_name}] ⚠️ Неизвестное окно после пополнения")
        return "error"

    def _parse_upgrade_timer(self, emulator: Dict) -> Optional[int]:
        """
        Спарсить таймер улучшения через иконку "Ускорить"

        Процесс:
        1. Найти и кликнуть иконку "Ускорить"
        2. Спарсить таймер в области TIMER_AREA
        3. Конвертировать в секунды
        4. Закрыть окно через ESC

        Returns:
            секунды или None (если таймер не найден - быстрое завершение)
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Парсинг таймера через 'Ускорить'...")

        # Попытка найти иконку "Ускорить" (до 5 секунд)
        for attempt in range(10):
            result = find_image(emulator, self.TEMPLATES['speedup_icon'],
                              threshold=self.THRESHOLD_ICON)

            if result:
                center_x, center_y = result

                logger.debug(f"[{emulator_name}] Найдена иконка 'Ускорить' на ({center_x}, {center_y})")
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)

                # Парсим таймер
                timer_seconds = self._extract_timer_from_window(emulator)

                # Закрываем окно
                press_key(emulator, "ESC")
                time.sleep(0.5)

                return timer_seconds

            time.sleep(0.5)

        # Иконка "Ускорить" не найдена - возможно быстрое завершение
        logger.info(f"[{emulator_name}] Иконка 'Ускорить' не найдена за 5 сек")
        return None

    def _extract_timer_from_window(self, emulator: Dict) -> Optional[int]:
        """
        Извлечь таймер из окна ускорения

        Формат: "10:41:48" или "1:10:41:48" (день:час:мин:сек)
        Область: TIMER_AREA
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        # Вырезаем область таймера
        x1, y1, x2, y2 = self.TIMER_AREA
        timer_region = screenshot[y1:y2, x1:x2]

        # Парсим через OCR
        results = self.ocr.recognize_text(timer_region, min_confidence=0.6)

        # Ищем паттерн таймера
        for elem in results:
            text = elem['text']

            # Паттерны: HH:MM:SS или D:HH:MM:SS
            pattern1 = r'(\d{1,2}):(\d{2}):(\d{2})'  # HH:MM:SS
            pattern2 = r'(\d+):(\d{1,2}):(\d{2}):(\d{2})'  # D:HH:MM:SS

            # Проверяем длинный формат
            match = re.search(pattern2, text)
            if match:
                days = int(match.group(1))
                hours = int(match.group(2))
                minutes = int(match.group(3))
                seconds = int(match.group(4))

                total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
                logger.debug(f"[{emulator_name}] Таймер (D:HH:MM:SS): {text} = {total_seconds} сек")
                return total_seconds

            # Проверяем короткий формат
            match = re.search(pattern1, text)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))

                total_seconds = hours * 3600 + minutes * 60 + seconds
                logger.debug(f"[{emulator_name}] Таймер (HH:MM:SS): {text} = {total_seconds} сек")
                return total_seconds

        logger.warning(f"[{emulator_name}] ⚠️ Не удалось спарсить таймер")
        return None

    def _format_time(self, seconds: int) -> str:
        """Форматировать секунды в читаемый вид"""
        if seconds < 60:
            return f"{seconds} сек"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} мин"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours} ч {minutes} мин"
        else:
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            return f"{days} д {hours} ч"