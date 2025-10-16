"""
Менеджер восстановления для обработки непредвиденных ситуаций
Универсальная система recovery для всего проекта Beast Lord Bot v3.0

Версия: 1.0
Дата создания: 2025-01-16
"""

import time
import os
from typing import Callable, Any, Optional, Dict
from functools import wraps
from utils.adb_controller import press_key
from utils.image_recognition import find_image, get_screenshot
from utils.logger import logger

# Базовая директория проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RecoveryManager:
    """
    Менеджер для обработки непредвиденных ситуаций и восстановления работы бота

    Основные возможности:
    - Очистка UI состояния через ESC
    - Обнаружение диалога выхода из игры
    - Повторные попытки операций с автоматическим recovery
    - Запрос на перезапуск эмулятора при критических ошибках

    Использование:
    ```python
    from utils.recovery_manager import recovery_manager

    # Очистка UI
    recovery_manager.clear_ui_state(emulator)

    # Обработка зависшего состояния
    recovery_manager.handle_stuck_state(emulator, context="Описание проблемы")

    # Запрос на перезапуск
    recovery_manager.request_emulator_restart(emulator, "Причина перезапуска")
    ```
    """

    # Шаблоны для определения состояния
    EXIT_DIALOG_TEMPLATE = os.path.join(BASE_DIR, 'data', 'templates', 'common', 'exit_dialog.png')

    # Настройки
    MAX_ESC_ATTEMPTS = 10  # Максимум нажатий ESC для очистки UI
    ESC_DELAY = 0.8  # Задержка между нажатиями ESC (секунды)

    def __init__(self):
        """Инициализация менеджера восстановления"""
        self.restart_requests = {}  # Хранение запросов на перезапуск {emulator_id: {reason, timestamp}}
        logger.debug("RecoveryManager инициализирован")

    def clear_ui_state(self, emulator: Dict, max_attempts: int = None) -> bool:
        """
        Очистить UI состояние через нажатия ESC

        Алгоритм:
        1. Нажимать ESC пока не появится диалог выхода "Хотите выйти из игры?"
        2. Когда диалог появился - нажать ESC еще раз для закрытия
        3. Это гарантирует чистое состояние (все окна закрыты)

        Args:
            emulator: объект эмулятора
            max_attempts: максимальное количество попыток (если None, используется значение по умолчанию)

        Returns:
            bool: True если удалось очистить UI
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")
        max_attempts = max_attempts or self.MAX_ESC_ATTEMPTS

        logger.info(f"[{emulator_name}] 🔄 Очистка UI состояния через ESC...")

        for attempt in range(1, max_attempts + 1):
            # Проверяем есть ли диалог выхода
            screenshot = get_screenshot(emulator)
            if screenshot is None:
                logger.error(f"[{emulator_name}] ❌ Не удалось получить скриншот")
                return False

            exit_dialog = find_image(emulator, self.EXIT_DIALOG_TEMPLATE, threshold=0.8)

            if exit_dialog is not None:
                # Диалог выхода найден - закрываем его
                logger.info(f"[{emulator_name}] ✅ Диалог выхода обнаружен на попытке {attempt}, закрываем...")
                press_key(emulator, "ESC")
                time.sleep(self.ESC_DELAY)

                # Проверяем что диалог закрылся
                screenshot = get_screenshot(emulator)
                exit_dialog_check = find_image(emulator, self.EXIT_DIALOG_TEMPLATE, threshold=0.8)

                if exit_dialog_check is None:
                    logger.success(f"[{emulator_name}] ✅ UI очищен успешно (попытка {attempt})")
                    return True
                else:
                    logger.warning(f"[{emulator_name}] ⚠️ Диалог не закрылся, повторяю...")
                    continue

            # Диалога нет - нажимаем ESC
            logger.debug(f"[{emulator_name}] Попытка {attempt}/{max_attempts}: нажатие ESC")
            press_key(emulator, "ESC")
            time.sleep(self.ESC_DELAY)

        logger.warning(f"[{emulator_name}] ⚠️ Не удалось полностью очистить UI за {max_attempts} попыток")
        return False

    def is_in_exit_dialog(self, emulator: Dict) -> bool:
        """
        Проверить находится ли бот в диалоге выхода

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если диалог выхода открыт
        """
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            return False

        exit_dialog = find_image(emulator, self.EXIT_DIALOG_TEMPLATE, threshold=0.8)
        return exit_dialog is not None

    def handle_stuck_state(self, emulator: Dict, context: str = "") -> bool:
        """
        Обработать зависшее состояние

        Используется когда операция не удалась и нужно восстановить состояние

        Args:
            emulator: объект эмулятора
            context: контекст ошибки (для логирования)

        Returns:
            bool: True если удалось восстановить состояние
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.warning(f"[{emulator_name}] ⚠️ Обнаружено зависшее состояние: {context}")

        # Пытаемся очистить UI
        success = self.clear_ui_state(emulator)

        if success:
            logger.info(f"[{emulator_name}] ✅ Состояние восстановлено")
        else:
            logger.error(f"[{emulator_name}] ❌ Не удалось восстановить состояние")

        return success

    def request_emulator_restart(self, emulator: Dict, reason: str):
        """
        Запросить перезапуск эмулятора

        Сохраняет запрос на перезапуск для обработки в BotOrchestrator

        Args:
            emulator: объект эмулятора
            reason: причина перезапуска
        """
        emulator_id = emulator.get('id')
        emulator_name = emulator.get('name', f"id:{emulator_id}")

        self.restart_requests[emulator_id] = {
            'reason': reason,
            'timestamp': time.time()
        }

        logger.warning(f"[{emulator_name}] 🔄 Запрошен перезапуск эмулятора: {reason}")

    def has_restart_request(self, emulator_id: int) -> bool:
        """
        Проверить есть ли запрос на перезапуск эмулятора

        Args:
            emulator_id: ID эмулятора

        Returns:
            bool: True если есть запрос
        """
        return emulator_id in self.restart_requests

    def get_restart_reason(self, emulator_id: int) -> Optional[str]:
        """
        Получить причину запроса на перезапуск

        Args:
            emulator_id: ID эмулятора

        Returns:
            str: причина или None
        """
        request = self.restart_requests.get(emulator_id)
        return request['reason'] if request else None

    def clear_restart_request(self, emulator_id: int):
        """
        Очистить запрос на перезапуск после обработки

        Args:
            emulator_id: ID эмулятора
        """
        if emulator_id in self.restart_requests:
            del self.restart_requests[emulator_id]
            logger.debug(f"Запрос на перезапуск эмулятора {emulator_id} очищен")


def retry_with_recovery(max_attempts: int = 2, recovery_between_attempts: bool = True):
    """
    Декоратор для автоматических повторных попыток с восстановлением

    Использование:
    ```python
    @retry_with_recovery(max_attempts=2, recovery_between_attempts=True)
    def my_method(self, emulator):
        # Ваш код
        # Вернуть True при успехе, False при неудаче
        pass
    ```

    Args:
        max_attempts: максимальное количество попыток (по умолчанию 2)
        recovery_between_attempts: выполнять ли recovery между попытками

    Returns:
        Результат функции или None при неудаче всех попыток
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, emulator: Dict, *args, **kwargs) -> Any:
            emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

            for attempt in range(1, max_attempts + 1):
                try:
                    logger.debug(f"[{emulator_name}] {func.__name__}: попытка {attempt}/{max_attempts}")

                    result = func(self, emulator, *args, **kwargs)

                    # Если результат успешный - возвращаем
                    if result:
                        if attempt > 1:
                            logger.success(f"[{emulator_name}] ✅ {func.__name__} успешен на попытке {attempt}")
                        return result

                    # Результат неуспешный
                    if attempt < max_attempts:
                        logger.warning(
                            f"[{emulator_name}] ⚠️ {func.__name__} неуспешен, попытка {attempt}/{max_attempts}")

                        # Выполняем recovery между попытками
                        if recovery_between_attempts:
                            logger.info(f"[{emulator_name}] 🔄 Восстановление перед повторной попыткой...")
                            recovery_mgr = RecoveryManager()
                            recovery_mgr.clear_ui_state(emulator)
                            time.sleep(1)  # Дополнительная пауза
                    else:
                        logger.error(f"[{emulator_name}] ❌ {func.__name__} не удался после {max_attempts} попыток")

                except Exception as e:
                    logger.error(f"[{emulator_name}] ❌ Ошибка в {func.__name__}: {e}")

                    if attempt < max_attempts and recovery_between_attempts:
                        logger.info(f"[{emulator_name}] 🔄 Восстановление после ошибки...")
                        recovery_mgr = RecoveryManager()
                        recovery_mgr.clear_ui_state(emulator)
                        time.sleep(1)

            return None

        return wrapper

    return decorator


# Глобальный экземпляр для использования во всем проекте
recovery_manager = RecoveryManager()