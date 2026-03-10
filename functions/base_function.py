# КЛЮЧЕВОЕ ИЗМЕНЕНИЕ v1.5: Добавлен session_state для мульти-pass (Wilds)
#
# session_state — словарь, который живёт пока эмулятор запущен.
# Передаётся между проходами function_executor.
# Каждая функция может читать/писать свою секцию:
#   self.session_state['wilds'] = { 'hunt_active': True, ... }
#
# Контракт execute() НЕ ИЗМЕНИЛСЯ:
#   return True  = "отработал, ситуация обработана"
#   return False = "сломался, нужна заморозка"
#   raise        = "баг, нужна заморозка"
#   return None  = трактуется как True (для совместимости)

"""
Базовый класс для всех игровых функций

ОБНОВЛЕНО v1.5:
- Добавлен session_state (dict) — общее состояние сессии эмулятора
- session_state передаётся между проходами function_executor
- Используется для мульти-pass логики (Wilds автоохота)
- Обратная совместимость: session_state опционален

Версия: 1.5
Дата обновления: 2025-03-10
"""

import traceback
from datetime import datetime
from typing import Optional
from utils.logger import logger


class BaseFunction:
    """
    Базовый класс для всех игровых функций

    Каждая функция должна:
    1. Проверять можно ли выполнять сейчас (can_execute)
    2. Выполнять свою логику (execute)
    3. Логировать результаты
    4. Сообщать планировщику КОГДА потребуется эмулятор (get_next_event_time)

    Контракт execute():
    - return True  → успех (или ситуация обработана, включая заморозку через БД)
    - return False → критическая ошибка → run() автоматически заморозит
    - return None  → трактуется как True (совместимость)
    - raise        → run() пробросит → function_executor заморозит
    """

    def __init__(self, emulator, session_state=None):
        """
        Args:
            emulator: dict с данными эмулятора (id, name, port)
            session_state: dict — общее состояние сессии эмулятора,
                           живёт пока эмулятор запущен, передаётся
                           между проходами function_executor.
                           Если None — создаётся пустой dict.
        """
        self.emulator = emulator
        self.emulator_name = emulator.get(
            'name', f"id:{emulator.get('id', '?')}"
        )
        self.name = "BaseFunction"
        self.session_state = session_state if session_state is not None else {}

        # Флаг критической ошибки (опциональный, для передачи причины)
        self._failed = False
        self._fail_reason = ""

    def can_execute(self):
        """
        Проверяет можно ли выполнять функцию сейчас
        Переопределяется в дочерних классах

        Returns:
            bool: True если функцию можно выполнять сейчас
        """
        return True

    def execute(self):
        """
        Основная логика выполнения функции
        Переопределяется в дочерних классах

        КОНТРАКТ:
        - return True  → успех
        - return False → критическая ошибка → автозаморозка
        - return None  → считается как True (совместимость)
        - raise        → function_executor заморозит

        ВАЖНО для "нехватка ресурсов" и подобных:
        Если функция САМА обработала ситуацию (заморозила через БД,
        поставила таймер и т.д.) — возвращай True, а не False.
        False = "я не смог обработать ситуацию, помогите".
        """
        raise NotImplementedError(f"{self.name}.execute() не реализован")

    def mark_failed(self, reason: str):
        """
        ОПЦИОНАЛЬНО пометить функцию как неуспешную С ПРИЧИНОЙ

        Используй если хочешь передать конкретную причину заморозки.
        Но можно просто return False из execute().

        Args:
            reason: причина ошибки (для лога и заморозки)
        """
        self._failed = True
        self._fail_reason = reason
        logger.warning(
            f"[{self.emulator_name}] ⚠️ {self.name} помечена как "
            f"неуспешная: {reason}"
        )

    def run(self):
        """
        Обёртка для выполнения с логированием и автозаморозкой

        ЛОГИКА:
        1. can_execute() ошибка → безопасный пропуск (return False)
        2. NotImplementedError → заглушка (return True)
        3. Exception в execute() → ПРОБРАСЫВАЕТСЯ → заморозка
        4. mark_failed() вызван → ПРОБРАСЫВАЕТСЯ → заморозка
        5. execute() вернул False → ПРОБРАСЫВАЕТСЯ → заморозка
        6. execute() вернул True/None → успех

        Returns:
            True — успешно выполнена
            False — пропущена (can_execute=False)
        Raises:
            Exception — при любой ошибке (для заморозки в function_executor)
        """
        # Сброс флага
        self._failed = False
        self._fail_reason = ""

        # Проверка can_execute (безопасная — ошибки НЕ пробрасываются)
        try:
            if not self.can_execute():
                logger.debug(
                    f"[{self.emulator_name}] Функция {self.name} "
                    f"пропущена (не готова)"
                )
                return False
        except Exception as e:
            logger.error(
                f"[{self.emulator_name}] Ошибка в {self.name}"
                f".can_execute(): {e}"
            )
            return False

        # Выполнение функции
        logger.info(f"[{self.emulator_name}] Выполнение: {self.name}")

        try:
            result = self.execute()
        except NotImplementedError:
            logger.debug(
                f"[{self.emulator_name}] Функция {self.name} "
                f"ещё не реализована (заглушка)"
            )
            return True
        except Exception as e:
            # ПРОБРАСЫВАЕМ — function_executor заморозит функцию
            logger.error(
                f"[{self.emulator_name}] ❌ Ошибка в {self.name}: {e}"
            )
            logger.error(
                f"[{self.emulator_name}] Traceback:\n"
                f"{traceback.format_exc()}"
            )
            raise

        # Проверяем флаг mark_failed()
        if self._failed:
            error_msg = (
                f"{self.name}: критическая ошибка — {self._fail_reason}"
            )
            logger.error(
                f"[{self.emulator_name}] ❌ {error_msg}"
            )
            raise RuntimeError(error_msg)

        # execute() вернул False → автозаморозка
        if result is False:
            error_msg = (
                f"{self.name}: execute() вернул False "
                f"(критическая ошибка в процессе выполнения)"
            )
            logger.error(
                f"[{self.emulator_name}] ❌ {error_msg}"
            )
            raise RuntimeError(error_msg)

        # Успех (True или None)
        logger.success(
            f"[{self.emulator_name}] Функция {self.name} завершена"
        )
        return True

    # ===== МЕТОД ДЛЯ ПЛАНИРОВЩИКА =====

    @staticmethod
    def get_next_event_time(emulator_id: int) -> Optional[datetime]:
        """
        Лёгкая проверка: КОГДА этой функции потребуется эмулятор?

        Вызывается планировщиком без запуска эмулятора.
        Переопределяется в дочерних классах.

        Returns:
            datetime — когда нужен эмулятор
            None — эмулятор не нужен для этой функции
        """
        return None