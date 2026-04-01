"""
Навигация и обучение войск

Полный цикл:
1. Клик по зданию (после navigate_to_building через NavigationPanel)
2. Поиск + клик иконки "Обучение"
3. Выбор тира (шаблон картинки юнита)
   - Всеядные: свайп влево к Т1
   - Плотоядные: Т4/Т5 видны сразу
4. OCR верификация названия + парсинг количества
5. Кнопка "Обучение" или "Восполнить ресурсы"
6. Парсинг таймера
7. ESC → возврат в поместье

Переиспользуемые шаблоны из building/:
- button_refill.png        — "Восполнить Ресурсы"
- button_confirm.png       — "Подтвердить"
- window_no_resources.png  — "Недостаточно ресурсов"

Отличие от строительства:
- После "Подтвердить" при восполнении ресурсов бот НЕ выкидывается
  из окна тренировки — тренировка запускается автоматически,
  и можно сразу парсить таймер.

Версия: 1.0
Дата создания: 2025-03-19
"""

import os
import re
import time
from typing import Dict, Optional, Tuple

from utils.adb_controller import tap, swipe, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.ocr_engine import OCREngine
from utils.logger import logger

from functions.training.training_database import (
    TROOP_INFO, UNIT_COUNT_REGION, TRAINING_TIMER_REGION,
    BUILDING_TYPE_NAMES_RU,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TrainingNavigation:
    """
    Навигация + обучение войск

    Предусловие: бот перешёл к зданию через NavigationPanel.navigate_to_building()
    и находится на главном экране поместья с видом на здание.
    """

    # ==================== КООРДИНАТЫ ====================

    # Центр здания после "Перейти"
    BUILDING_CENTER = (268, 517)

    # Свайп для всеядных: к Т1 (вправо → влево, плавный)
    OMNIVORE_SWIPE = {
        'x1': 32, 'y1': 645,
        'x2': 519, 'y2': 645,
        'duration': 800,  # Плавный свайп
    }

    # ==================== ШАБЛОНЫ ====================

    TEMPLATES = {
        # Иконка "Обучение" на здании (после клика по зданию)
        'training_icon': os.path.join(
            BASE_DIR, 'data', 'templates', 'training', 'training_icon.png'
        ),

        # Кнопка "Обучение" (запуск тренировки)
        'button_training': os.path.join(
            BASE_DIR, 'data', 'templates', 'training', 'button_training.png'
        ),

        # Иконка "Обучение" уменьшённая (тренировка уже идёт)
        'training_icon_active': os.path.join(
            BASE_DIR, 'data', 'templates', 'training', 'training_icon_active.png'
        ),

        # Шаблоны тиров юнитов (картинки животных)
        'tier4_carnivore': os.path.join(
            BASE_DIR, 'data', 'templates', 'training', 'tier4_carnivore.png'
        ),
        'tier5_carnivore': os.path.join(
            BASE_DIR, 'data', 'templates', 'training', 'tier5_carnivore.png'
        ),
        'tier1_omnivore': os.path.join(
            BASE_DIR, 'data', 'templates', 'training', 'tier1_omnivore.png'
        ),

        # Переиспользуемые из building/
        'button_refill': os.path.join(
            BASE_DIR, 'data', 'templates', 'building', 'button_refill.png'
        ),
        'button_confirm': os.path.join(
            BASE_DIR, 'data', 'templates', 'building', 'button_confirm.png'
        ),
        'window_no_resources': os.path.join(
            BASE_DIR, 'data', 'templates', 'building', 'window_no_resources.png'
        ),
    }

    # Пороги
    THRESHOLD_ICON = 0.65
    THRESHOLD_BUTTON = 0.85
    THRESHOLD_WINDOW = 0.85
    THRESHOLD_TIER = 0.80

    def __init__(self):
        self.ocr = OCREngine()

        # Проверяем шаблоны
        for name, path in self.TEMPLATES.items():
            exists = os.path.exists(path)
            status = "✅" if exists else "❌"
            logger.debug(f"{status} Шаблон training '{name}': {path}")

        logger.info("✅ TrainingNavigation инициализирована")

    # ==================== ГЛАВНЫЙ МЕТОД ====================

    def train_troops(
        self,
        emulator: Dict,
        building_type: str,
        tier: int,
    ) -> Tuple[str, Optional[int], Optional[int]]:
        """
        Полный цикл обучения войск

        Предусловие: бот перешёл к зданию через NavigationPanel

        Args:
            emulator: dict эмулятора
            building_type: 'carnivore' / 'omnivore'
            tier: тир юнита (1, 4, 5)

        Returns:
            (status, timer_seconds, unit_count)

            status:
                "started"          — тренировка запущена
                "no_resources"     — нехватка ресурсов
                "already_training" — слот уже занят (иконка обучения не найдена)
                "error"            — ошибка навигации / OCR

            timer_seconds: время тренировки (сек) или None
            unit_count: количество юнитов (парсинг "Имеется:") или None
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        type_name = BUILDING_TYPE_NAMES_RU.get(building_type, building_type)

        logger.info(
            f"[{emu_name}] 🎓 Начало обучения: {type_name} Т{tier}"
        )

        # ШАГ 1: Клик по зданию
        self._click_building(emulator)

        # ШАГ 2: Поиск и клик иконки "Обучение"
        if not self._click_training_icon(emulator):
            logger.warning(
                f"[{emu_name}] ⚠️ Иконка 'Обучение' не найдена — "
                f"возможно, уже тренируется"
            )
            press_key(emulator, "ESC")
            time.sleep(0.5)
            return "already_training", None, None

        # ШАГ 3: Выбор тира
        if not self._select_tier(emulator, building_type, tier):
            logger.error(
                f"[{emu_name}] ❌ Не удалось выбрать Т{tier}"
            )
            press_key(emulator, "ESC")
            time.sleep(0.5)
            return "error", None, None

        # ШАГ 4: Верификация названия юнита
        if not self._verify_unit_name(emulator, building_type, tier):
            logger.warning(
                f"[{emu_name}] ⚠️ Название юнита не совпадает с ожидаемым"
            )
            # Не прерываем — возможно OCR неточен, но шаблон нашёлся

        # ШАГ 5: Парсинг количества юнитов
        unit_count = self._parse_unit_count(emulator)

        # ШАГ 6: Обработка окна тренировки (кнопки)
        training_result = self._handle_training_window(emulator)

        if training_result == "no_resources":
            logger.warning(
                f"[{emu_name}] ❌ Недостаточно ресурсов для {type_name} Т{tier}"
            )
            return "no_resources", None, unit_count

        if training_result == "error":
            logger.error(
                f"[{emu_name}] ❌ Ошибка при обработке окна тренировки"
            )
            return "error", None, unit_count

        # ШАГ 7: Парсинг таймера
        timer_seconds = self._parse_training_timer(emulator)

        # ШАГ 8: ESC — закрыть окно тренировки
        press_key(emulator, "ESC")
        time.sleep(0.5)

        if timer_seconds:
            logger.success(
                f"[{emu_name}] ✅ {type_name} Т{tier}: тренировка запущена "
                f"({self._format_time(timer_seconds)})"
            )
        else:
            logger.success(
                f"[{emu_name}] ✅ {type_name} Т{tier}: тренировка запущена "
                f"(таймер не распознан)"
            )

        return "started", timer_seconds, unit_count

    # ==================== ЧАСТНЫЕ МЕТОДЫ ====================

    def _click_building(self, emulator: Dict):
        """Клик по зданию в центре экрана"""
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(
            f"[{emu_name}] Клик по зданию "
            f"({self.BUILDING_CENTER[0]}, {self.BUILDING_CENTER[1]})"
        )
        tap(emulator, x=self.BUILDING_CENTER[0], y=self.BUILDING_CENTER[1])
        time.sleep(1.5)

    def _click_training_icon(self, emulator: Dict) -> bool:
        """
        Найти и кликнуть иконку "Обучение" на здании.

        Ищет два шаблона:
        - training_icon        — обычный размер (слот свободен)
        - training_icon_active — уменьшённый (тренировка уже идёт)

        Returns:
            True — иконка найдена и нажата
            False — не найдена
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        logger.debug(f"[{emu_name}] Поиск иконки 'Обучение'...")

        icon_keys = ['training_icon', 'training_icon_active']

        for attempt in range(3):
            for key in icon_keys:
                template_path = self.TEMPLATES.get(key)
                if not template_path or not os.path.exists(template_path):
                    continue

                result = find_image(
                    emulator, template_path,
                    threshold=self.THRESHOLD_ICON,
                )
                if result:
                    cx, cy = result
                    logger.debug(
                        f"[{emu_name}] Иконка 'Обучение' ({key}) "
                        f"найдена: ({cx}, {cy})"
                    )
                    tap(emulator, x=cx, y=cy)
                    time.sleep(1.5)
                    return True

            time.sleep(0.5)

        logger.warning(f"[{emu_name}] ⚠️ Иконка 'Обучение' не найдена")
        return False

    def _select_tier(self, emulator: Dict, building_type: str,
                     tier: int) -> bool:
        """
        Выбрать тир юнита (клик по шаблону картинки)

        Для всеядных: свайп влево к Т1 + задержка 2сек перед поиском.
        Для плотоядных: Т4/Т5 видны сразу.

        Returns:
            True — шаблон найден и нажат
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Определяем шаблон
        template_key = self._get_tier_template_key(building_type, tier)
        if not template_key:
            logger.error(
                f"[{emu_name}] Нет шаблона для {building_type} Т{tier}"
            )
            return False

        template_path = self.TEMPLATES.get(template_key)
        if not template_path or not os.path.exists(template_path):
            logger.error(
                f"[{emu_name}] ❌ Файл шаблона не найден: {template_key}"
            )
            return False

        # Для всеядных — свайп к Т1
        if building_type == 'omnivore':
            logger.debug(f"[{emu_name}] Свайп влево к Т1 всеядных...")
            s = self.OMNIVORE_SWIPE
            swipe(emulator, s['x1'], s['y1'], s['x2'], s['y2'], s['duration'])
            time.sleep(2)  # Задержка перед поиском шаблона (из ТЗ)

        # Поиск шаблона тира
        logger.debug(f"[{emu_name}] Поиск шаблона {template_key}...")

        for attempt in range(3):
            result = find_image(
                emulator, template_path,
                threshold=self.THRESHOLD_TIER,
            )
            if result:
                cx, cy = result
                logger.debug(
                    f"[{emu_name}] Шаблон Т{tier} найден: ({cx}, {cy})"
                )
                tap(emulator, x=cx, y=cy)
                time.sleep(1.0)
                return True

            time.sleep(0.5)

        logger.error(
            f"[{emu_name}] ❌ Шаблон {template_key} не найден"
        )
        return False

    def _verify_unit_name(self, emulator: Dict, building_type: str,
                          tier: int) -> bool:
        """
        OCR верификация названия юнита

        Парсит текст в области имени и сравнивает с ожидаемым.
        НЕ блокирует процесс при несовпадении — только предупреждение.

        Returns:
            True — название совпало
            False — не совпало или не удалось распознать
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        troop_info = TROOP_INFO.get(building_type, {}).get(tier)
        if not troop_info:
            logger.warning(
                f"[{emu_name}] Нет данных о юните {building_type} Т{tier}"
            )
            return False

        expected_name = troop_info['name']
        region = troop_info['name_region']

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        elements = self.ocr.recognize_text(
            screenshot, region=region, min_confidence=0.3
        )

        if not elements:
            logger.warning(
                f"[{emu_name}] OCR не распознал текст в области имени"
            )
            return False

        # Собираем весь текст из области
        parsed_text = ' '.join(e['text'] for e in elements).strip()
        logger.debug(
            f"[{emu_name}] OCR имя юнита: '{parsed_text}' "
            f"(ожидалось: '{expected_name}')"
        )

        # Нечёткое сравнение: ожидаемое имя содержится в распознанном
        parsed_lower = parsed_text.lower().replace(' ', '')
        expected_lower = expected_name.lower().replace(' ', '')

        if expected_lower in parsed_lower or parsed_lower in expected_lower:
            logger.debug(f"[{emu_name}] ✅ Название юнита совпадает")
            return True

        # Дополнительная проверка: хотя бы первое слово совпадает
        first_word_expected = expected_name.split()[0].lower()
        if first_word_expected in parsed_lower:
            logger.debug(
                f"[{emu_name}] ✅ Частичное совпадение "
                f"('{first_word_expected}' найдено)"
            )
            return True

        logger.warning(
            f"[{emu_name}] ⚠️ Название не совпадает: "
            f"'{parsed_text}' ≠ '{expected_name}'"
        )
        return False

    def _parse_unit_count(self, emulator: Dict) -> Optional[int]:
        """
        Парсинг количества юнитов из "Имеется: 14,720"

        Область: UNIT_COUNT_REGION (186, 126, 353, 151)
        Формат: "Имеется: XX,XXX" — запятая = разделитель тысяч

        Returns:
            int: количество юнитов или None
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        x1, y1, x2, y2 = UNIT_COUNT_REGION
        elements = self.ocr.recognize_text(
            screenshot, region=(x1, y1, x2, y2), min_confidence=0.3
        )

        if not elements:
            logger.warning(
                f"[{emu_name}] OCR не распознал количество юнитов"
            )
            return None

        full_text = ' '.join(e['text'] for e in elements).strip()
        logger.debug(f"[{emu_name}] OCR количество: '{full_text}'")

        # Ищем число с запятыми: "14,720" или "1,234,567"
        # Также поддерживаем без запятых: "14720"
        number_pattern = r'(\d[\d,]*\d|\d+)'
        match = re.search(number_pattern, full_text)

        if match:
            number_str = match.group(1).replace(',', '')
            try:
                count = int(number_str)
                logger.debug(f"[{emu_name}] Количество юнитов: {count:,}")
                return count
            except ValueError:
                pass

        logger.warning(
            f"[{emu_name}] ⚠️ Не удалось извлечь число из '{full_text}'"
        )
        return None

    def _handle_training_window(self, emulator: Dict) -> str:
        """
        Обработка окна тренировки

        Сценарии:
        1. Кнопка "Обучение" → клик → тренировка началась
        2. Кнопка "Восполнить Ресурсы" → клик →
           2а. "Подтвердить" → клик → остаёмся в окне, тренировка авто-стартует
           2б. "Подтвердить" → клик → "Недостаточно ресурсов"
           2в. Сразу "Недостаточно ресурсов" (нет в рюкзаке)
        3. Ни одной кнопки → ошибка

        ВАЖНОЕ ОТЛИЧИЕ ОТ СТРОИТЕЛЬСТВА:
        После "Подтвердить" при восполнении ресурсов, бот НЕ выкидывается
        из окна тренировки. Тренировка запускается автоматически.

        Returns:
            "started"      — тренировка запущена
            "no_resources" — нехватка ресурсов
            "error"        — непредвиденная ситуация
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # === ВАРИАНТ 1: Кнопка "Обучение" ===
        result = find_image(
            emulator, self.TEMPLATES['button_training'],
            threshold=self.THRESHOLD_BUTTON,
        )
        if result:
            cx, cy = result
            logger.debug(f"[{emu_name}] Найдена кнопка 'Обучение'")
            tap(emulator, x=cx, y=cy)
            time.sleep(2)
            return "started"

        # === ВАРИАНТ 2: Кнопка "Восполнить Ресурсы" ===
        result = find_image(
            emulator, self.TEMPLATES['button_refill'],
            threshold=self.THRESHOLD_BUTTON,
        )
        if result:
            logger.debug(f"[{emu_name}] Найдена кнопка 'Восполнить Ресурсы'")
            cx, cy = result
            tap(emulator, x=cx, y=cy)
            time.sleep(2)

            return self._handle_refill_window(emulator)

        # === ВАРИАНТ 3: Ничего не найдено ===
        logger.warning(
            f"[{emu_name}] ⚠️ Ни 'Обучение', ни 'Восполнить Ресурсы' "
            f"не найдены"
        )
        press_key(emulator, "ESC")
        time.sleep(0.5)
        return "error"

    def _handle_refill_window(self, emulator: Dict) -> str:
        """
        Обработка окна восполнения ресурсов

        ОТЛИЧИЕ ОТ СТРОИТЕЛЬСТВА:
        После "Подтвердить" при тренировке:
        - Закрывается ТОЛЬКО окно восполнения
        - Бот остаётся в окне тренировки
        - Тренировка запускается автоматически
        → Можно сразу парсить таймер

        Returns:
            "started"      — ресурсы восполнены, тренировка авто-стартовала
            "no_resources" — недостаточно ресурсов
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Проверяем: сразу "Недостаточно ресурсов"?
        if find_image(
            emulator, self.TEMPLATES['window_no_resources'],
            threshold=self.THRESHOLD_WINDOW,
        ):
            logger.warning(
                f"[{emu_name}] ⚠️ Сразу 'Недостаточно ресурсов' — "
                f"в рюкзаке нет нужных ресурсов"
            )
            # ESC×2: закрыть окно нехватки + окно тренировки
            press_key(emulator, "ESC")
            time.sleep(0.5)
            press_key(emulator, "ESC")
            time.sleep(0.5)
            return "no_resources"

        # Ищем кнопку "Подтвердить"
        confirm = find_image(
            emulator, self.TEMPLATES['button_confirm'],
            threshold=self.THRESHOLD_BUTTON,
        )

        if not confirm:
            logger.warning(
                f"[{emu_name}] ⚠️ 'Подтвердить' не найдена"
            )
            press_key(emulator, "ESC")
            time.sleep(0.5)
            press_key(emulator, "ESC")
            time.sleep(0.5)
            return "no_resources"

        # Клик "Подтвердить"
        cx, cy = confirm
        logger.debug(f"[{emu_name}] Клик 'Подтвердить' ({cx}, {cy})")
        tap(emulator, x=cx, y=cy)
        time.sleep(2)

        # Проверяем: появилось ли "Недостаточно ресурсов" после подтверждения?
        if find_image(
            emulator, self.TEMPLATES['window_no_resources'],
            threshold=self.THRESHOLD_WINDOW,
        ):
            logger.warning(
                f"[{emu_name}] ⚠️ 'Недостаточно ресурсов' после распаковки"
            )
            press_key(emulator, "ESC")
            time.sleep(0.5)
            press_key(emulator, "ESC")
            time.sleep(0.5)
            return "no_resources"

        # Ресурсы восполнены → тренировка автоматически запустилась
        logger.debug(
            f"[{emu_name}] ✅ Ресурсы восполнены, тренировка авто-стартовала"
        )
        return "started"

    def _parse_training_timer(self, emulator: Dict) -> Optional[int]:
        """
        Парсинг таймера обучения

        Область: TRAINING_TIMER_REGION (210, 803, 330, 837)
        Формат: "HH:MM:SS" или "D:HH:MM:SS"

        Returns:
            int: секунды или None
        """
        emu_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return None

        x1, y1, x2, y2 = TRAINING_TIMER_REGION
        elements = self.ocr.recognize_text(
            screenshot, region=(x1, y1, x2, y2), min_confidence=0.5
        )

        for elem in elements:
            text = elem['text'].strip()

            # Формат D:HH:MM:SS
            match = re.search(r'(\d+):(\d{1,2}):(\d{2}):(\d{2})', text)
            if match:
                days = int(match.group(1))
                hours = int(match.group(2))
                minutes = int(match.group(3))
                seconds = int(match.group(4))
                total = days * 86400 + hours * 3600 + minutes * 60 + seconds
                logger.debug(
                    f"[{emu_name}] ⏱️ Таймер тренировки: {text} = {total}с"
                )
                return total

            # Формат HH:MM:SS
            match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})', text)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))
                total = hours * 3600 + minutes * 60 + seconds
                logger.debug(
                    f"[{emu_name}] ⏱️ Таймер тренировки: {text} = {total}с"
                )
                return total

        logger.warning(
            f"[{emu_name}] ⚠️ Не удалось спарсить таймер тренировки"
        )
        return None

    # ==================== УТИЛИТЫ ====================

    @staticmethod
    def _get_tier_template_key(building_type: str, tier: int) -> Optional[str]:
        """Получить ключ шаблона для тира"""
        mapping = {
            ('carnivore', 4): 'tier4_carnivore',
            ('carnivore', 5): 'tier5_carnivore',
            ('omnivore', 1): 'tier1_omnivore',
        }
        return mapping.get((building_type, tier))

    @staticmethod
    def _format_time(seconds: int) -> str:
        """Форматировать секунды в читаемый вид"""
        if seconds < 60:
            return f"{seconds} сек"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} мин"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}ч {minutes}мин"
        else:
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            return f"{days}д {hours}ч"