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
        'button_upgrade_grey': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'button_upgrade_grey.png'),
        'button_upgrade': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'button_upgrade.png'),
        'button_refill': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'button_refill.png'),
        'button_confirm': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'button_confirm.png'),

        # Окна
        'window_refill': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'window_refill.png'),
        'window_no_resources': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'window_no_resources.png'),
    }

    # Пороги для поиска изображений
    THRESHOLD_ICON = 0.65  # Для иконок (могут быть разных размеров)
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
        2. Кнопка "Восполнить Ресурсы" - автопополнение из рюкзака
           2а. После "Подтвердить" ресурсы распакованы → стройка началась
           2б. После "Подтвердить" всё равно нехватка → окно "Недостаточно ресурсов"

        Returns:
            "started" - улучшение началось
            "no_resources" - нехватка ресурсов
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ШАГ 0: Ищем кнопку "Улучшение" (любую — серую или зелёную)
        # Пробуем оба шаблона, берём лучшее совпадение
        button_location = self._find_upgrade_button(emulator)

        if button_location:
            bx, by = button_location
            # Определяем цвет кнопки через HSV
            color = self._check_button_color(emulator, bx, by)

            if color == 'grey':
                logger.warning(f"[{emulator_name}] ⚠️ Кнопка 'Улучшение' серая — "
                               f"не выполнено условие")
                press_key(emulator, "ESC")
                time.sleep(0.5)
                return "requirements_not_met"

            elif color == 'green':
                logger.debug(f"[{emulator_name}] Кнопка 'Улучшение' зелёная — кликаем")
                tap(emulator, x=bx, y=by)
                time.sleep(1.5)
                return "started"

            else:
                # Неопределённый цвет — на всякий случай пробуем кликнуть
                logger.warning(f"[{emulator_name}] ⚠️ Цвет кнопки неопределён, пробуем кликнуть")
                tap(emulator, x=bx, y=by)
                time.sleep(1.5)
                return "started"

        # ПРОВЕРКА 2: Кнопка "Восполнить Ресурсы"
        if find_image(emulator, self.TEMPLATES['button_refill'],
                     threshold=self.THRESHOLD_BUTTON):
            logger.debug(f"[{emulator_name}] Найдена кнопка 'Восполнить Ресурсы'")

            result = find_image(emulator, self.TEMPLATES['button_refill'],
                              threshold=self.THRESHOLD_BUTTON)
            if result:
                center_x, center_y = result
                tap(emulator, x=center_x, y=center_y)
                time.sleep(1.5)

            # Обработка окна подтверждения
            return self._handle_refill_window(emulator)

        logger.warning(f"[{emulator_name}] ⚠️ Не найдена кнопка улучшения")
        return "error"

    def _find_upgrade_button(self, emulator: Dict):
        """
        Найти кнопку 'Улучшение' на экране (любого цвета).
        Пробует оба шаблона, возвращает координаты лучшего совпадения.
        """
        from utils.image_recognition import get_screenshot
        import cv2

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        best_val = 0
        best_loc = None
        best_template = None

        for key in ('button_upgrade', 'button_upgrade_grey'):
            path = self.TEMPLATES[key]
            if not os.path.exists(path):
                continue
            template = cv2.imread(path)
            if template is None:
                continue

            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > best_val and max_val >= 0.75:
                best_val = max_val
                best_loc = max_loc
                best_template = template

        if best_loc and best_template is not None:
            h, w = best_template.shape[:2]
            cx = best_loc[0] + w // 2
            cy = best_loc[1] + h // 2
            logger.debug(f"Кнопка 'Улучшение' найдена: ({cx}, {cy}), confidence={best_val:.3f}")
            return (cx, cy)

        return None

    def _check_button_color(self, emulator: Dict, cx: int, cy: int) -> str:
        """
        Определить цвет кнопки 'Улучшение' через HSV-анализ.

        Вырезает небольшой регион вокруг центра кнопки и считает
        соотношение зелёных и серых пикселей.

        Returns:
            'green', 'grey' или 'unknown'
        """
        from utils.image_recognition import get_screenshot
        import cv2

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return 'unknown'

        # Вырезаем регион кнопки (±30px по X, ±10px по Y от центра)
        h, w = screenshot.shape[:2]
        x1 = max(0, cx - 30)
        x2 = min(w, cx + 30)
        y1 = max(0, cy - 10)
        y2 = min(h, cy + 10)

        crop = screenshot[y1:y2, x1:x2]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # Зелёный диапазон (кнопка "Улучшение" зелёная)
        green_mask = cv2.inRange(hsv, (35, 60, 60), (85, 255, 255))
        green_count = cv2.countNonZero(green_mask)

        # Серый диапазон (низкая насыщенность = серый)
        grey_mask = cv2.inRange(hsv, (0, 0, 40), (180, 50, 180))
        grey_count = cv2.countNonZero(grey_mask)

        total = crop.shape[0] * crop.shape[1]
        green_pct = green_count / total if total > 0 else 0
        grey_pct = grey_count / total if total > 0 else 0

        logger.debug(f"🎨 Кнопка HSV: green={green_pct:.1%}, grey={grey_pct:.1%}")

        if green_pct > grey_pct and green_pct > 0.15:
            return 'green'
        elif grey_pct > green_pct and grey_pct > 0.15:
            return 'grey'

        return 'unknown'

    def _handle_refill_window(self, emulator: Dict) -> str:
        """
        Обработать окно после клика "Восполнить Ресурсы"

        Три подсценария:
        2а. Окно с "Подтвердить" → клик → стройка началась
        2б. Окно с "Подтвердить" → клик → "Недостаточно ресурсов"
            (часть ресурсов распакована, но остальных нет в рюкзаке)
        2в. Сразу окно "Недостаточно ресурсов"
            (в рюкзаке вообще нет нужных ресурсов)

        Returns:
            "started" - ресурсы пополнены, постройка началась
            "no_resources" - недостаточно ресурсов
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # ШАГ 1: Проверяем — сразу "Недостаточно ресурсов"? (вариант 2в)
        if find_image(emulator, self.TEMPLATES['window_no_resources'],
                     threshold=self.THRESHOLD_WINDOW):
            logger.warning(f"[{emulator_name}] ⚠️ Сразу окно 'Недостаточно ресурсов' — "
                          f"в рюкзаке нет нужных ресурсов")

            # 2×ESC для закрытия
            press_key(emulator, "ESC")
            time.sleep(0.5)
            press_key(emulator, "ESC")
            time.sleep(0.5)

            return "no_resources"

        # ШАГ 2: Ищем кнопку "Подтвердить" (варианты 2а / 2б)
        confirm_result = find_image(emulator, self.TEMPLATES['button_confirm'],
                                   threshold=self.THRESHOLD_BUTTON)

        if not confirm_result:
            logger.warning(f"[{emulator_name}] ⚠️ Ни 'Недостаточно ресурсов', ни 'Подтвердить' не найдены")
            press_key(emulator, "ESC")
            time.sleep(0.5)
            return "error"

        # ШАГ 3: Клик "Подтвердить"
        center_x, center_y = confirm_result
        logger.debug(f"[{emulator_name}] Клик 'Подтвердить' ({center_x}, {center_y})")
        tap(emulator, x=center_x, y=center_y)
        time.sleep(2)

        # ШАГ 4: Проверяем результат — что произошло после подтверждения?
        # Вариант 2б: После распаковки всё равно нехватка
        if find_image(emulator, self.TEMPLATES['window_no_resources'],
                     threshold=self.THRESHOLD_WINDOW):
            logger.warning(f"[{emulator_name}] ⚠️ Окно 'Недостаточно ресурсов' после распаковки — "
                          f"часть ресурсов распакована, но остальных нет в рюкзаке")

            # 2×ESC для закрытия
            press_key(emulator, "ESC")
            time.sleep(0.5)
            press_key(emulator, "ESC")
            time.sleep(0.5)

            return "no_resources"

        # Вариант 2а: Окна нехватки нет — стройка началась
        logger.debug(f"[{emulator_name}] ✅ Ресурсы восполнены, стройка началась")
        return "started"

    def _parse_upgrade_timer(self, emulator: Dict) -> Optional[int]:
        """
        Спарсить таймер улучшения через иконку "Ускорить"

        УЛУЧШЕНО: Множественные пороги + OCR fallback

        Процесс:
        1. Найти и кликнуть иконку "Ускорить" (template matching с разными порогами)
        2. Если не нашли - fallback на OCR поиск текста "Ускорить"
        3. Спарсить таймер в области TIMER_AREA
        4. Конвертировать в секунды
        5. Закрыть окно через ESC

        Returns:
            секунды или None (если таймер не найден - быстрое завершение)
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] Парсинг таймера через 'Ускорить'...")

        # ============== ПОПЫТКА 1: TEMPLATE MATCHING С РАЗНЫМИ ПОРОГАМИ ==============
        # Пробуем разные пороги от высокого к низкому
        thresholds = [0.75, 0.65, 0.55]

        for threshold in thresholds:
            logger.debug(f"[{emulator_name}] 🔍 Поиск иконки 'Ускорить' (порог {threshold})...")

            for attempt in range(3):  # 3 попытки на каждый порог
                result = find_image(emulator, self.TEMPLATES['speedup_icon'],
                                    threshold=threshold)

                if result:
                    center_x, center_y = result

                    logger.success(
                        f"[{emulator_name}] ✅ Найдена иконка 'Ускорить' на ({center_x}, {center_y}) с порогом {threshold}")
                    tap(emulator, x=center_x, y=center_y)
                    time.sleep(1.5)

                    # Парсим таймер
                    timer_seconds = self._extract_timer_from_window(emulator)

                    # Закрываем окно
                    press_key(emulator, "ESC")
                    time.sleep(0.5)

                    return timer_seconds

                time.sleep(0.3)

            logger.debug(f"[{emulator_name}] ⚠️ Иконка не найдена с порогом {threshold}")

        # ============== ПОПЫТКА 2: OCR FALLBACK ==============
        logger.warning(f"[{emulator_name}] ⚠️ Template matching не сработал, пробую OCR fallback...")

        speedup_coords = self._find_speedup_by_ocr(emulator)

        if speedup_coords:
            center_x, center_y = speedup_coords

            logger.success(f"[{emulator_name}] ✅ Найден текст 'Ускорить' через OCR на ({center_x}, {center_y})")
            tap(emulator, x=center_x, y=center_y)
            time.sleep(1.5)

            # Парсим таймер
            timer_seconds = self._extract_timer_from_window(emulator)

            # Закрываем окно
            press_key(emulator, "ESC")
            time.sleep(0.5)

            return timer_seconds

        # ============== НИЧЕГО НЕ НАШЛИ - БЫСТРОЕ ЗАВЕРШЕНИЕ ==============
        logger.info(f"[{emulator_name}] 🚀 Иконка 'Ускорить' не найдена за все попытки - возможно быстрое завершение")
        return None

    def _find_speedup_by_ocr(self, emulator: Dict) -> Optional[Tuple[int, int]]:
        """
        Найти кнопку "Ускорить" через OCR (fallback метод)

        Returns:
            (x, y) координаты кнопки или None
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] 🔍 Поиск текста 'Ускорить' через OCR...")

        # Получаем скриншот
        from utils.image_recognition import get_screenshot
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        # Распознаём текст на экране
        elements = self.ocr.recognize_text(screenshot, min_confidence=0.3)

        # Ищем слово "Ускорить" или "скорить" (может быть обрезано)
        for elem in elements:
            text_lower = elem['text'].lower().replace(' ', '')

            if 'ускорить' in text_lower or 'скорить' in text_lower or 'ускорит' in text_lower:
                logger.debug(f"[{emulator_name}] 📝 OCR нашёл: '{elem['text']}' на ({elem['x']}, {elem['y']})")

                # Возвращаем координаты центра текста
                # Смещаем немного вправо (там где иконка)
                x = elem['x'] + 30
                y = elem['y']

                return (x, y)

        logger.warning(f"[{emulator_name}] ⚠️ OCR не нашёл текст 'Ускорить'")
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