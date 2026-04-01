"""
Функция: MailRewardsFunction — сбор наград с почты

Полусервисная функция:
  Режим 1 (сервисный): 1 раз за сессию при hunt_active=True
  Режим 2 (самостоятельный): если > 48ч без сбора → самотриггер

Алгоритм:
  1. Из поместья открыть почту tap(204, 915)
  2. Верификация заголовка "Почта" (template match)
  3. Обход 3 вкладок (События → Студия Beast Lord → Система):
     a. Клик по вкладке
     b. HSV-проверка кнопки "Быстрое Чтение":
        - Серая → ESC (закрыть вкладку)
        - Зелёная → tap(кнопка) → проверка окна наград (лоза):
          • Есть → ESC (награды) → ESC (вкладка)
          • Нет  → ESC (вкладка)
  4. После последней вкладки: ESC (закрыть почту)
  5. Обновить last_collected_at в БД

Контракт execute():
  return True  = обработано (собрано / нечего собирать)
  return False = критическая ошибка → автозаморозка

Версия: 1.0
"""

import os
import time
from datetime import datetime
from typing import Dict, Optional

import cv2

from functions.base_function import BaseFunction
from functions.mail_rewards.mail_storage import MailStorage, SELF_TRIGGER_HOURS
from utils.adb_controller import tap, press_key
from utils.image_recognition import find_image, get_screenshot
from utils.function_freeze_manager import function_freeze_manager
from utils.logger import logger

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# ==================== КООРДИНАТЫ (540×960) ====================

# Открыть почту из поместья
COORD_OPEN_MAIL = (204, 915)

# Вкладки почты (обход сверху вниз)
MAIL_TABS = [
    {'name': 'События',            'coords': (146, 373)},
    {'name': 'Студия Beast Lord',   'coords': (146, 462)},
    {'name': 'Система',             'coords': (146, 549)},
]

# Кнопка "Быстрое Чтение" — фиксированная позиция
QUICK_READ_REGION = (167, 896, 365, 931)   # (x1, y1, x2, y2) для HSV-кропа
QUICK_READ_CENTER = (266, 913)              # Центр для клика

# ==================== ТАЙМИНГИ ====================

DELAY_AFTER_OPEN_MAIL = 1.5
DELAY_AFTER_TAB_CLICK = 1.0
DELAY_AFTER_QUICK_READ = 1.5
DELAY_AFTER_ESC = 0.8


class MailRewardsFunction(BaseFunction):
    """
    Полусервисная функция сбора наград с почты

    Режим 1 (сервисный): при wilds hunt_active=True, 1 раз за сессию
    Режим 2 (самостоятельный): самотриггер через 48ч без сбора
    """

    FUNCTION_NAME = 'mail_rewards'

    # Шаблоны
    TEMPLATES = {
        'mail_header': os.path.join(
            BASE_DIR, 'data', 'templates', 'mail_rewards', 'mail_header.png'
        ),
        'reward_popup_loz': os.path.join(
            BASE_DIR, 'data', 'templates', 'mail_rewards', 'reward_popup_loz.png'
        ),
    }

    # Пороги
    THRESHOLD_HEADER = 0.8
    THRESHOLD_REWARD = 0.75

    # HSV диапазоны для кнопки "Быстрое Чтение"
    GREEN_HSV_LOW = (35, 60, 60)
    GREEN_HSV_HIGH = (85, 255, 255)
    GREY_HSV_LOW = (0, 0, 40)
    GREY_HSV_HIGH = (180, 50, 180)

    def __init__(self, emulator, session_state=None):
        super().__init__(emulator, session_state)
        self.name = "MailRewardsFunction"

        self._storage = None
        self._navigation = None

        logger.info(
            f"[{self.emulator_name}] ✅ MailRewardsFunction инициализирована"
        )

    # ==================== ЛЕНИВЫЕ СВОЙСТВА ====================

    @property
    def storage(self) -> MailStorage:
        if self._storage is None:
            self._storage = MailStorage()
        return self._storage

    @property
    def navigation(self):
        """WildsNavigation для ensure_in_estate()"""
        if self._navigation is None:
            from functions.wilds.wilds_navigation import WildsNavigation
            self._navigation = WildsNavigation()
        return self._navigation

    # ==================== ПЛАНИРОВЩИК ====================

    @staticmethod
    def get_next_event_time(emulator_id: int) -> Optional[datetime]:
        """
        Когда сбору почты потребуется эмулятор?

        Логика:
        1. Заморожена → время разморозки
        2. Нет записи в БД → datetime.now() (первый запуск, нужен сразу)
        3. last_collected + 48ч <= now → datetime.now() (самотриггер)
        4. Иначе → None (сервисная, не триггерит)

        Returns:
            datetime или None
        """
        # 1. Заморожена?
        if function_freeze_manager.is_frozen(emulator_id, 'mail_rewards'):
            unfreeze = function_freeze_manager.get_unfreeze_time(
                emulator_id, 'mail_rewards'
            )
            return unfreeze

        storage = MailStorage()

        # 2. Нет записи → первый запуск, нужен сразу
        if not storage.has_data(emulator_id):
            return datetime.now()

        # 3. Просрочено (> 48ч)?
        if storage.is_overdue(emulator_id):
            return datetime.now()

        # 4. Не просрочено → сервисная
        return None

    # ==================== can_execute ====================

    def can_execute(self) -> bool:
        """
        Можно ли собирать почту сейчас?

        Условия:
        1. Не заморожена
        2. Не done в этой сессии
        3. Первый запуск (нет записи в БД) → разрешаем
        4. РЕЖИМ СЕРВИСНЫЙ: wilds в active_functions + hunt_active=True
        5. РЕЖИМ САМОСТОЯТЕЛЬНЫЙ: last_collected > 48ч назад

        Returns:
            True — можно выполнять execute()
            False — пропускаем
        """
        emu_id = self.emulator.get('id')

        # 1. Заморожена?
        if function_freeze_manager.is_frozen(emu_id, self.FUNCTION_NAME):
            return False

        # 2. Уже выполнялась в этой сессии?
        mail_state = self.session_state.get('mail_rewards', {})
        if mail_state.get('done', False):
            logger.debug(
                f"[{self.emulator_name}] 📬 Почта: "
                f"уже собрано в этой сессии"
            )
            return False

        # 3. Первый запуск: нет записи в БД → нужно собрать
        if not self.storage.has_data(emu_id):
            logger.info(
                f"[{self.emulator_name}] 📬 Почта: "
                f"первый запуск (нет записи в БД)"
            )
            return True

        # 4. Режим сервисный: wilds активна + hunt_active
        active_funcs = self.session_state.get('_active_functions', [])
        has_wilds = 'wilds' in active_funcs

        if has_wilds:
            wilds_state = self.session_state.get('wilds', {})
            if wilds_state.get('hunt_active', False):
                logger.debug(
                    f"[{self.emulator_name}] 📬 Почта: "
                    f"сервисный режим (hunt_active=True)"
                )
                return True

        # 5. Режим самостоятельный: просрочено > 48ч
        if self.storage.is_overdue(emu_id):
            logger.info(
                f"[{self.emulator_name}] 📬 Почта: "
                f"самотриггер (> {SELF_TRIGGER_HOURS}ч без сбора)"
            )
            return True

        logger.debug(
            f"[{self.emulator_name}] 📬 Почта: пропуск — "
            f"нет триггера"
        )
        return False

    # ==================== execute ====================

    def execute(self) -> bool:
        """
        Собрать награды с почты.

        Алгоритм:
        1. Убедиться что в поместье
        2. Открыть почту → верификация заголовка
        3. Обход 3 вкладок с HSV-проверкой кнопки
        4. Закрыть почту
        5. Обновить БД

        Returns:
            True  — обработано (собрано или нечего собирать)
            False — критическая ошибка → автозаморозка
        """
        emu_id = self.emulator.get('id')

        logger.info(
            f"[{self.emulator_name}] 📬 Начинаю сбор наград с почты"
        )

        # 1. Убедиться что в поместье
        if not self.navigation.ensure_in_estate(self.emulator):
            logger.error(
                f"[{self.emulator_name}] ❌ Не удалось вернуться в поместье"
            )
            return False

        # 2. Открыть почту
        if not self._open_mail():
            logger.error(
                f"[{self.emulator_name}] ❌ Не удалось открыть почту"
            )
            return False

        # 3. Обход вкладок
        collected_any = False

        for i, tab in enumerate(MAIL_TABS):
            tab_name = tab['name']
            tab_coords = tab['coords']
            is_last = (i == len(MAIL_TABS) - 1)

            logger.info(
                f"[{self.emulator_name}] 📬 Вкладка: {tab_name}"
            )

            result = self._process_tab(tab_name, tab_coords)

            if result == 'collected':
                collected_any = True
            elif result == 'error':
                # Ошибка навигации внутри вкладки — пытаемся восстановиться
                logger.warning(
                    f"[{self.emulator_name}] ⚠️ Ошибка во вкладке "
                    f"{tab_name}, пробую продолжить"
                )
                press_key(self.emulator, "ESC")
                time.sleep(DELAY_AFTER_ESC)

        # 4. Закрыть почту (ESC после последней вкладки)
        press_key(self.emulator, "ESC")
        time.sleep(DELAY_AFTER_ESC)

        # 5. Обновить БД
        self.storage.update_collected(emu_id)

        # 6. Пометить done в session_state
        self.session_state.setdefault('mail_rewards', {})['done'] = True

        if collected_any:
            logger.success(
                f"[{self.emulator_name}] ✅ Награды с почты собраны!"
            )
        else:
            logger.info(
                f"[{self.emulator_name}] 📬 Нечего собирать — "
                f"все кнопки серые"
            )

        return True

    # ==================== ОТКРЫТИЕ ПОЧТЫ ====================

    def _open_mail(self) -> bool:
        """
        Открыть окно почты и верифицировать заголовок.

        Returns:
            True — почта открыта и верифицирована
            False — не удалось открыть
        """
        for attempt in range(1, 4):
            logger.debug(
                f"[{self.emulator_name}] Открытие почты "
                f"(попытка {attempt}/3)"
            )

            tap(self.emulator, *COORD_OPEN_MAIL)
            time.sleep(DELAY_AFTER_OPEN_MAIL)

            # Верификация заголовка "Почта"
            result = find_image(
                self.emulator,
                self.TEMPLATES['mail_header'],
                threshold=self.THRESHOLD_HEADER
            )

            if result is not None:
                logger.debug(
                    f"[{self.emulator_name}] ✅ Заголовок 'Почта' найден"
                )
                return True

            logger.warning(
                f"[{self.emulator_name}] ⚠️ Заголовок 'Почта' не найден, "
                f"попытка {attempt}/3"
            )

            # ESC + повтор
            press_key(self.emulator, "ESC")
            time.sleep(DELAY_AFTER_ESC)

        return False

    # ==================== ОБРАБОТКА ВКЛАДКИ ====================

    def _process_tab(self, tab_name: str, tab_coords: tuple) -> str:
        """
        Обработать одну вкладку почты.

        Алгоритм:
        1. Клик по вкладке
        2. HSV-проверка кнопки "Быстрое Чтение"
        3. Серая → ESC → 'empty'
        4. Зелёная → клик → проверка лозы → ESC(ы) → 'collected'

        Args:
            tab_name: название вкладки (для логов)
            tab_coords: (x, y) координаты вкладки

        Returns:
            'collected' — награды собраны
            'empty'     — кнопка серая, нечего собирать
            'error'     — ошибка
        """
        # 1. Клик по вкладке
        tap(self.emulator, *tab_coords)
        time.sleep(DELAY_AFTER_TAB_CLICK)

        # 2. Проверить цвет кнопки "Быстрое Чтение"
        color = self._check_quick_read_color()

        if color == 'grey':
            logger.info(
                f"[{self.emulator_name}] 📬 {tab_name}: "
                f"кнопка серая, пропускаем"
            )
            press_key(self.emulator, "ESC")
            time.sleep(DELAY_AFTER_ESC)
            return 'empty'

        if color == 'green':
            logger.info(
                f"[{self.emulator_name}] 📬 {tab_name}: "
                f"кнопка зелёная, собираем!"
            )
            return self._collect_tab_rewards(tab_name)

        # unknown — на всякий случай пробуем кликнуть
        logger.warning(
            f"[{self.emulator_name}] ⚠️ {tab_name}: "
            f"цвет кнопки не определён, пробуем кликнуть"
        )
        return self._collect_tab_rewards(tab_name)

    def _collect_tab_rewards(self, tab_name: str) -> str:
        """
        Кликнуть "Быстрое Чтение" и обработать результат.

        Args:
            tab_name: название вкладки (для логов)

        Returns:
            'collected' — награды собраны (или письма без наград)
            'error'     — ошибка
        """
        # Клик по кнопке
        tap(self.emulator, *QUICK_READ_CENTER)
        time.sleep(DELAY_AFTER_QUICK_READ)

        # Проверяем — появилось ли окно с наградами (шаблон лозы)?
        reward_found = find_image(
            self.emulator,
            self.TEMPLATES['reward_popup_loz'],
            threshold=self.THRESHOLD_REWARD
        )

        if reward_found is not None:
            # Есть окно наград → ESC (закрыть награды) → ESC (закрыть вкладку)
            logger.info(
                f"[{self.emulator_name}] 🎁 {tab_name}: "
                f"награды получены!"
            )
            press_key(self.emulator, "ESC")
            time.sleep(DELAY_AFTER_ESC)
            press_key(self.emulator, "ESC")
            time.sleep(DELAY_AFTER_ESC)
        else:
            # Нет окна наград (письма без наград) → кнопка стала серой → ESC
            logger.info(
                f"[{self.emulator_name}] 📬 {tab_name}: "
                f"письма без наград прочитаны"
            )
            press_key(self.emulator, "ESC")
            time.sleep(DELAY_AFTER_ESC)

        return 'collected'

    # ==================== HSV-АНАЛИЗ КНОПКИ ====================

    def _check_quick_read_color(self) -> str:
        """
        Определить цвет кнопки "Быстрое Чтение" через HSV-анализ.

        Кропает фиксированный регион QUICK_READ_REGION,
        считает зелёные vs серые пиксели.

        Returns:
            'green' — кнопка зелёная (есть что собрать)
            'grey'  — кнопка серая (нечего собирать)
            'unknown' — не удалось определить
        """
        screenshot = get_screenshot(self.emulator)
        if screenshot is None:
            logger.error(
                f"[{self.emulator_name}] ❌ Не удалось получить скриншот "
                f"для проверки кнопки"
            )
            return 'unknown'

        x1, y1, x2, y2 = QUICK_READ_REGION
        crop = screenshot[y1:y2, x1:x2]

        if crop.size == 0:
            logger.warning(
                f"[{self.emulator_name}] ⚠️ Пустой кроп кнопки"
            )
            return 'unknown'

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # Подсчёт зелёных пикселей
        green_mask = cv2.inRange(hsv, self.GREEN_HSV_LOW, self.GREEN_HSV_HIGH)
        green_count = cv2.countNonZero(green_mask)

        # Подсчёт серых пикселей
        grey_mask = cv2.inRange(hsv, self.GREY_HSV_LOW, self.GREY_HSV_HIGH)
        grey_count = cv2.countNonZero(grey_mask)

        total = crop.shape[0] * crop.shape[1]
        green_pct = green_count / total if total > 0 else 0
        grey_pct = grey_count / total if total > 0 else 0

        logger.debug(
            f"[{self.emulator_name}] 🎨 Быстрое Чтение HSV: "
            f"green={green_pct:.1%}, grey={grey_pct:.1%}"
        )

        if green_pct > grey_pct and green_pct > 0.15:
            return 'green'
        elif grey_pct > green_pct and grey_pct > 0.15:
            return 'grey'

        return 'unknown'