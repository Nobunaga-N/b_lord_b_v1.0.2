# КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: run() автоматически замораживает при execute()→False
#
# Новый контракт execute():
#   return True  = "отработал, ситуация обработана"
#                  (включая "нет ресурсов → заморозил себя")
#   return False = "сломался, нужна заморозка"
#   raise        = "баг, нужна заморозка"
#   return None  = трактуется как True (для совместимости)
#
# mark_failed() остаётся как ОПЦИОНАЛЬНЫЙ инструмент для передачи
# конкретной причины. Но он НЕ ОБЯЗАТЕЛЕН — False сам по себе
# запускает заморозку.
#
# Показан ПОЛНЫЙ файл.

"""
Базовый класс для всех игровых функций

ОБНОВЛЕНО v1.4:
- run() автоматически замораживает при execute()→False
- mark_failed() теперь ОПЦИОНАЛЕН (не нужен в каждой функции)
- Новый контракт: True=обработано, False=ошибка, raise=баг

Версия: 1.4
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

    Контракт execute():
    - return True  → успех (или ситуация обработана, включая заморозку через БД)
    - return False → критическая ошибка → run() автоматически заморозит
    - return None  → трактуется как True (совместимость)
    - raise        → run() пробросит → function_executor заморозит
    """

    def __init__(self, emulator):
        self.emulator = emulator
        self.emulator_name = emulator.get(
            'name', f"id:{emulator.get('id', '?')}"
        )
        self.name = "BaseFunction"

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
        Если не вызвать — run() всё равно заморозит при False,
        но причина будет общей.

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
        5. execute() вернул False → ПРОБРАСЫВАЕТСЯ → заморозка  ← НОВОЕ
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
            raise  # ← function_executor поймает и заморозит

        # Проверяем флаг mark_failed() (опционально, для причины)
        if self._failed:
            error_msg = (
                f"{self.name}: критическая ошибка — {self._fail_reason}"
            )
            logger.error(
                f"[{self.emulator_name}] ❌ {error_msg}"
            )
            raise RuntimeError(error_msg)  # ← function_executor заморозит

        # ===== НОВОЕ: execute() вернул False → автозаморозка =====
        if result is False:
            error_msg = (
                f"{self.name}: execute() вернул False "
                f"(критическая ошибка в процессе выполнения)"
            )
            logger.error(
                f"[{self.emulator_name}] ❌ {error_msg}"
            )
            raise RuntimeError(error_msg)  # ← function_executor заморозит

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