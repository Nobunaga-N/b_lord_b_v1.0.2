"""
Менеджер заморозки функций при критических ошибках

При критической ошибке в функции — замораживает её на указанное время
для конкретного эмулятора. Остальные функции продолжают работать.

Версия: 1.0
Дата создания: 2025-02-19
"""

import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from utils.logger import logger


class FunctionFreezeManager:
    """
    Менеджер заморозки функций

    Хранит в памяти: {(emulator_id, function_name): unfreeze_datetime}
    Thread-safe через Lock.
    """

    DEFAULT_FREEZE_HOURS = 4

    def __init__(self):
        self._freezes: Dict[tuple, datetime] = {}
        self._lock = threading.Lock()

    def freeze(self, emulator_id: int, function_name: str,
               hours: float = None, reason: str = ""):
        """
        Заморозить функцию для эмулятора

        Args:
            emulator_id: ID эмулятора
            function_name: имя функции (building, research, и т.д.)
            hours: на сколько часов заморозить (по умолчанию 4)
            reason: причина заморозки (для лога)
        """
        hours = hours or self.DEFAULT_FREEZE_HOURS
        key = (emulator_id, function_name)
        unfreeze_at = datetime.now() + timedelta(hours=hours)

        with self._lock:
            self._freezes[key] = unfreeze_at

        logger.warning(
            f"🧊 Функция '{function_name}' заморожена для эмулятора {emulator_id} "
            f"на {hours}ч (до {unfreeze_at.strftime('%H:%M:%S')}). "
            f"Причина: {reason}"
        )

    def is_frozen(self, emulator_id: int, function_name: str) -> bool:
        """
        Проверить заморожена ли функция

        Автоматически разморозит если время вышло.

        Returns:
            True если функция заморожена
        """
        key = (emulator_id, function_name)

        with self._lock:
            if key not in self._freezes:
                return False

            if datetime.now() >= self._freezes[key]:
                # Время вышло — разморозить
                del self._freezes[key]
                logger.info(
                    f"🔓 Функция '{function_name}' разморожена "
                    f"для эмулятора {emulator_id}"
                )
                return False

            return True

    def get_unfreeze_time(self, emulator_id: int,
                          function_name: str) -> Optional[datetime]:
        """Получить время разморозки (или None если не заморожена)"""
        key = (emulator_id, function_name)
        with self._lock:
            return self._freezes.get(key)

    def get_frozen_functions(self, emulator_id: int) -> List[str]:
        """Получить список замороженных функций для эмулятора"""
        now = datetime.now()
        result = []

        with self._lock:
            for (emu_id, func_name), unfreeze_at in list(self._freezes.items()):
                if emu_id == emulator_id:
                    if now >= unfreeze_at:
                        del self._freezes[(emu_id, func_name)]
                    else:
                        result.append(func_name)

        return result

    def unfreeze(self, emulator_id: int, function_name: str):
        """Принудительно разморозить функцию"""
        key = (emulator_id, function_name)
        with self._lock:
            if key in self._freezes:
                del self._freezes[key]
                logger.info(
                    f"🔓 Функция '{function_name}' принудительно "
                    f"разморожена для эмулятора {emulator_id}"
                )

    def unfreeze_all(self, emulator_id: int):
        """Разморозить все функции для эмулятора"""
        with self._lock:
            keys_to_remove = [
                k for k in self._freezes if k[0] == emulator_id
            ]
            for key in keys_to_remove:
                del self._freezes[key]

    def get_all_freezes(self) -> Dict[tuple, datetime]:
        """Получить все заморозки (для отладки)"""
        with self._lock:
            return dict(self._freezes)


# Глобальный экземпляр
function_freeze_manager = FunctionFreezeManager()