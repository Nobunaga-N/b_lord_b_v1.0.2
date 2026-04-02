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
from typing import Dict, Optional, Tuple, List
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
        'upgrade_icon_small': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'upgrade_icon_small.png'),
        'speedup_icon': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'speedup_icon.png'),
        'speedup_icon_small': os.path.join(BASE_DIR, 'data', 'templates', 'building', 'speedup_icon_small.png'),

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

    def upgrade_building(
        self,
        emulator: Dict,
        building_name: str,
        building_index: Optional[int] = None,
        keep_speedup_open: bool = False,
    ) -> Tuple[bool, Optional[int]]:
        """
        ГЛАВНЫЙ МЕТОД - Улучшить здание

        Предусловие: бот уже перешел к зданию через navigate_to_building()

        Args:
            emulator: объект эмулятора
            building_name: название здания
            building_index: индекс (для множественных зданий)
            keep_speedup_open: если True — окно ускорений остаётся открытым
                               после парсинга таймера (для prime time drain,
                               чтобы не навигировать повторно к тому же зданию)

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
            logger.warning(
                f"[{emulator_name}] ❌ Недостаточно ресурсов "
                f"для {building_display}"
            )
            return False, None

        elif upgrade_result == "started":
            logger.success(
                f"[{emulator_name}] ✅ Улучшение началось: {building_display}"
            )

            # ШАГ 4: Парсинг таймера
            # ✅ FIX: передаём keep_speedup_open
            timer_seconds = self._parse_upgrade_timer(
                emulator, keep_speedup_open=keep_speedup_open
            )

            if timer_seconds is None:
                logger.info(
                    f"[{emulator_name}] 🚀 Возможно быстрое завершение "
                    f"(помощь альянса)"
                )
                return True, 0

            logger.info(
                f"[{emulator_name}] ⏱️ Таймер улучшения: "
                f"{self._format_time(timer_seconds)}"
            )
            return True, timer_seconds

        else:
            logger.error(
                f"[{emulator_name}] ❌ Неизвестная ошибка при улучшении"
            )
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
        Найти и кликнуть иконку "Улучшить" на здании.
        Ищет два шаблона: стандартный и уменьшённый.

        Returns:
            True — иконка найдена и нажата
            False — не найдена
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        logger.debug(f"[{emulator_name}] Поиск иконки 'Улучшить'...")

        result = self._find_icon_variants(
            emulator,
            template_keys=['upgrade_icon', 'upgrade_icon_small'],
            thresholds=[self.THRESHOLD_ICON],
            label="Улучшить",
        )

        if result:
            center_x, center_y = result
            tap(emulator, x=center_x, y=center_y)
            time.sleep(1.5)
            return True

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

    def _parse_upgrade_timer(
        self,
        emulator: Dict,
        keep_speedup_open: bool = False,
    ) -> Optional[int]:
        """
        Спарсить таймер улучшения через клик по иконке "Ускорить".

        Алгоритм:
        1. Найти иконку "Ускорить" (2 шаблона + OCR fallback)
        2. Клик → открыть окно ускорений
        3. Спарсить таймер в области TIMER_AREA
        4. Конвертировать в секунды
        5. Закрыть окно через ESC (если keep_speedup_open=False)

        Args:
            emulator: объект эмулятора
            keep_speedup_open: если True — НЕ закрывать окно ускорений.
                               Используется для prime time drain.

        Returns:
        секунды или None (если таймер не найден — быстрое завершение)
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        logger.debug(f"[{emulator_name}] Парсинг таймера через 'Ускорить'...")

        # Поиск иконки (2 шаблона + OCR fallback)
        icon_pos = self._find_speedup_icon(emulator)

        if icon_pos:
            center_x, center_y = icon_pos
            logger.success(
                f"[{emulator_name}] ✅ Найдена иконка 'Ускорить' "
                f"на ({center_x}, {center_y})"
            )
            tap(emulator, x=center_x, y=center_y)
            time.sleep(1.5)

            # Парсим таймер
            timer_seconds = self._extract_timer_from_window(emulator)

            # Закрываем только если НЕ keep_speedup_open
            if not keep_speedup_open:
                press_key(emulator, "ESC")
                time.sleep(0.5)

            return timer_seconds

        # Ничего не нашли — быстрое завершение
        logger.info(
            f"[{emulator_name}] 🚀 Иконка 'Ускорить' не найдена "
            f"— возможно быстрое завершение"
        )
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

    def _open_speedup_window(self, emulator: Dict) -> bool:
        """
        Открыть окно ускорения (клик по иконке "Ускорить").
        НЕ закрывает окно после открытия.

        Returns:
        bool: True если окно открыто
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        icon_pos = self._find_speedup_icon(emulator)

        if icon_pos:
            center_x, center_y = icon_pos
            tap(emulator, x=center_x, y=center_y)
            time.sleep(1.5)
            return True

        logger.warning(f"[{emulator_name}] ❌ Не удалось открыть окно ускорений")
        return False

    def speedup_lord(self, emulator: Dict) -> Dict:
        """
        Автоускорение Лорда после постановки на улучшение.

        Вызывается ПОСЛЕ upgrade_building() вернул (True, timer > 0).
        Бот находится на экране здания (окно ускорения закрыто).

        Алгоритм:
        1. Кликнуть "Ускорить" → открыть окно
        2. Спарсить таймер
        3. Кликнуть "Автоускорение"
        4. Три сценария:
           a1) "Подтвердить" → Лорд мгновенно (кнопка "Автоускорение" пропала)
           a2) "Подтвердить" → не хватило ("Автоускорение" видна) → парсим остаток
           б)  "Подтвердить" не появилась → нет ускорялок вообще

        Returns:
            dict: {'status': str, 'timer_seconds': int|None}
            status: 'instant_upgrade' | 'timer_remaining' | 'no_speedups' | 'error'
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.info(f"[{emulator_name}] 👑 Автоускорение Лорда...")

        # ШАГ 1: Открыть окно ускорения
        if not self._open_speedup_window(emulator):
            logger.warning(f"[{emulator_name}] ⚠️ Не удалось открыть окно ускорения — "
                           f"возможно Лорд уже улучшился мгновенно")
            return {'status': 'instant_upgrade', 'timer_seconds': None}

        # ШАГ 2: Парсим таймер
        initial_timer = self._extract_timer_from_window(emulator)
        if initial_timer:
            logger.info(f"[{emulator_name}] ⏱️ Таймер Лорда до ускорения: "
                        f"{self._format_time(initial_timer)}")

        # ШАГ 3: Кликнуть "Автоускорение"
        auto_btn = find_image(
            emulator, self.TEMPLATES['button_auto_speedup'],
            threshold=self.THRESHOLD_BUTTON
        )

        if not auto_btn:
            logger.warning(f"[{emulator_name}] ⚠️ Кнопка 'Автоускорение' не найдена")
            press_key(emulator, "ESC")
            time.sleep(0.5)
            return {'status': 'error', 'timer_seconds': initial_timer}

        cx, cy = auto_btn
        logger.debug(f"[{emulator_name}] Клик 'Автоускорение' ({cx}, {cy})")
        tap(emulator, x=cx, y=cy)
        time.sleep(2)

        # ШАГ 4: Ищем "Подтвердить"
        confirm = find_image(
            emulator, self.TEMPLATES['button_confirm'],
            threshold=self.THRESHOLD_BUTTON
        )

        if confirm:
            # ═══ СЦЕНАРИЙ (а): Окно подтверждения появилось ═══
            logger.info(f"[{emulator_name}] ✅ Кликаем 'Подтвердить'")
            tap(emulator, x=confirm[0], y=confirm[1])
            time.sleep(3)

            # Проверяем: осталась ли "Автоускорение"?
            auto_check = find_image(
                emulator, self.TEMPLATES['button_auto_speedup'],
                threshold=self.THRESHOLD_BUTTON
            )

            if auto_check:
                # ─── (а2): Ускорений не хватило ───
                logger.info(f"[{emulator_name}] ⏳ Ускорений не хватило")
                remaining = self._extract_timer_from_window(emulator)
                if remaining:
                    logger.info(f"[{emulator_name}] ⏱️ Осталось: {self._format_time(remaining)}")
                press_key(emulator, "ESC")
                time.sleep(0.5)
                return {'status': 'timer_remaining', 'timer_seconds': remaining}
            else:
                # ─── (а1): Лорд улучшился мгновенно ───
                logger.success(f"[{emulator_name}] 👑🎉 Лорд улучшился мгновенно!")
                return {'status': 'instant_upgrade', 'timer_seconds': None}

        else:
            # ═══ СЦЕНАРИЙ (б): "Подтвердить" не появилась — ускорялок нет ═══
            logger.info(f"[{emulator_name}] ⚠️ Ускорялок нет на аккаунте")

            # Повторный клик "Автоускорение" для вызова окна "Нет предметов"
            auto_retry = find_image(
                emulator, self.TEMPLATES['button_auto_speedup'],
                threshold=self.THRESHOLD_BUTTON
            )

            if auto_retry:
                tap(emulator, x=auto_retry[0], y=auto_retry[1])
                time.sleep(2)

                # Ищем шаблон "Нет предметов ускорения"
                no_items = find_image(
                    emulator, self.TEMPLATES['window_no_speedup_items'],
                    threshold=self.THRESHOLD_WINDOW
                )
                if no_items:
                    logger.info(f"[{emulator_name}] ✅ Подтверждено: нет предметов ускорения")

                # Парсим время
                remaining = self._extract_timer_from_window(emulator)
                if remaining:
                    logger.info(f"[{emulator_name}] ⏱️ Время: {self._format_time(remaining)}")

                press_key(emulator, "ESC")
                time.sleep(0.5)
                return {'status': 'no_speedups', 'timer_seconds': remaining}

            # Fallback: "Автоускорение" тоже пропала
            logger.warning(f"[{emulator_name}] ⚠️ Кнопка 'Автоускорение' пропала")
            return {'status': 'instant_upgrade', 'timer_seconds': None}

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

    def _find_icon_variants(
        self,
        emulator: Dict,
        template_keys: List[str],
        thresholds: Optional[List[float]] = None,
        max_attempts: int = 3,
        label: str = "иконка",
    ) -> Optional[Tuple[int, int]]:
        """
        Поиск иконки по нескольким шаблонам (стандартный + уменьшённый)
        с каскадом порогов.

        Логика: для каждого порога перебираем ВСЕ шаблоны,
        для каждого шаблона — max_attempts попыток.
        Первое совпадение — возврат.

        Args:
            emulator: объект эмулятора
            template_keys: ключи в self.TEMPLATES (например ['speedup_icon', 'speedup_icon_small'])
            thresholds: список порогов (по убыванию). None → [0.75, 0.65, 0.55]
            max_attempts: попыток на каждый шаблон×порог
            label: название для логов

        Returns:
            (x, y) координаты центра или None
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        if thresholds is None:
            thresholds = [0.75, 0.65, 0.55]

        for threshold in thresholds:
            for key in template_keys:
                template_path = self.TEMPLATES.get(key)
                if not template_path or not os.path.exists(template_path):
                    continue

                for attempt in range(max_attempts):
                    result = find_image(
                        emulator, template_path,
                        threshold=threshold,
                    )
                    if result:
                        center_x, center_y = result
                        logger.debug(
                            f"[{emulator_name}] ✅ {label} ({key}) "
                            f"найдена: ({center_x}, {center_y}), "
                            f"порог {threshold}"
                        )
                        return (center_x, center_y)

                    time.sleep(0.3)

            logger.debug(
                f"[{emulator_name}] ⚠️ {label} не найдена "
                f"с порогом {threshold}"
            )

        return None

    def _find_speedup_icon(
        self,
        emulator: Dict,
    ) -> Optional[Tuple[int, int]]:
        """
        Найти иконку "Ускорить" — два шаблона + OCR fallback.

        Returns:
            (x, y) координаты центра или None
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] 🔍 Поиск иконки 'Ускорить'...")

        # Попытка 1: Template matching (стандартная + уменьшённая)
        result = self._find_icon_variants(
            emulator,
            template_keys=['speedup_icon', 'speedup_icon_small'],
            label="Ускорить",
        )
        if result:
            return result

        # Попытка 2: OCR fallback
        logger.warning(
            f"[{emulator_name}] ⚠️ Template matching не сработал, "
            f"пробую OCR fallback..."
        )
        ocr_result = self._find_speedup_by_ocr(emulator)
        if ocr_result:
            logger.debug(
                f"[{emulator_name}] ✅ 'Ускорить' через OCR "
                f"({ocr_result[0]}, {ocr_result[1]})"
            )
            return ocr_result

        logger.warning(f"[{emulator_name}] ❌ Иконка 'Ускорить' не найдена")
        return None