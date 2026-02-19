"""
Базовый класс для всех игровых функций

ОБНОВЛЕНО:
- Добавлен mark_failed() для сигнализации о критических ошибках
- run() пробрасывает исключения в function_executor для заморозки
- can_execute() ошибки НЕ пробрасываются (безопасный пропуск)

Версия: 1.3
Дата обновления: 2025-02-19
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
    5. Вызывать self.mark_failed() при критических ошибках внутри execute()
    """

    def __init__(self, emulator):
        self.emulator = emulator
        self.emulator_name = emulator.get(
            'name', f"id:{emulator.get('id', '?')}"
        )
        self.name = "BaseFunction"

        # Флаг критической ошибки (для функций которые сами ловят ошибки)
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
        """
        raise NotImplementedError(f"{self.name}.execute() не реализован")

    def mark_failed(self, reason: str):
        """
        Пометить функцию как неуспешную

        Вызывается из execute() дочернего класса когда произошла
        критическая ошибка, но функция сама поймала исключение.

        После завершения execute() метод run() проверит этот флаг
        и пробросит исключение в function_executor для заморозки.

        Пример использования в дочернем классе:
            try:
                self._do_something()
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                self.mark_failed(f"Ошибка: {e}")
                return  # Не нужно raise — run() сделает это сам

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
        Обертка для выполнения с логированием

        ЛОГИКА ПРОБРАСЫВАНИЯ ОШИБОК:
        1. Ошибка в can_execute() → безопасный пропуск (return False)
        2. NotImplementedError → заглушка (return True)
        3. Exception в execute() → ПРОБРАСЫВАЕТСЯ в function_executor
        4. mark_failed() → ПРОБРАСЫВАЕТСЯ как RuntimeError

        function_executor ловит исключения и замораживает функцию на 4 часа.

        Returns:
            True — успешно выполнена
            False — пропущена (can_execute=False или ошибка в can_execute)
        Raises:
            Exception — при ошибке в execute() (для заморозки в function_executor)
            RuntimeError — при mark_failed() (для заморозки в function_executor)
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
            self.execute()
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
            raise  # ← function_executor поймает и заморозит

        # Проверяем флаг mark_failed()
        if self._failed:
            error_msg = (
                f"{self.name}: критическая ошибка — {self._fail_reason}"
            )
            logger.error(
                f"[{self.emulator_name}] ❌ {error_msg}"
            )
            raise RuntimeError(error_msg)  # ← function_executor заморозит

        logger.success(
            f"[{self.emulator_name}] Функция {self.name} завершена"
        )
        return True

    # ===== МЕТОД ДЛЯ ПЛАНИРОВЩИКА =====

    @staticmethod
    def get_next_event_time(emulator_id: int) -> Optional[datetime]:
        """
        Лёгкая проверка: КОГДА этой функции потребуется эмулятор?

        Вызывается планировщиком в главном цикле БЕЗ запуска эмулятора.
        Работает ТОЛЬКО с БД / конфигами / текущим временем.
        НЕ использует OCR, ADB, скриншоты — ничего, что требует работающий эмулятор.

        Переопределяется в дочерних классах при реализации функционала.
        Функции-заглушки (ещё не реализованные) возвращают None —
        планировщик не будет запускать эмулятор ради них.

        Returns:
            datetime.min      → НЕМЕДЛЕННО (новый эмулятор, первичное сканирование)
            datetime (прошлое) → ПРОСРОЧЕНО (событие уже наступило, нужен сейчас)
            datetime (будущее) → ЗАПЛАНИРОВАНО (событие наступит в указанное время)
            None               → НЕ НУЖЕН (всё сделано / функция не реализована)
        """
        return None