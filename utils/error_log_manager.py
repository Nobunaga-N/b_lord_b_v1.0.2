"""
Менеджер журнала критических ошибок
Собирает ERROR и CRITICAL логи с контекстом для анализа
"""

import os
import threading
from datetime import datetime
from typing import List, Dict, Optional
from collections import deque


class ErrorLogManager:
    """
    Менеджер для сбора критических ошибок с контекстом

    Функционал:
    - Автоматический сбор ERROR/CRITICAL из логов
    - Хранение ±20 строк контекста вокруг ошибки
    - Привязка к ID и названию эмулятора
    - Thread-safe операции
    """

    def __init__(self, context_lines: int = 20):
        """
        Инициализация менеджера

        Args:
            context_lines: количество строк контекста до и после ошибки
        """
        self.context_lines = context_lines

        # Хранилище ошибок
        self._errors: List[Dict] = []

        # Буфер последних строк лога (для контекста)
        self._log_buffer = deque(maxlen=context_lines)

        # Буфер для строк после ошибки
        self._after_error_buffer = []
        self._collecting_after = 0  # Счетчик строк после ошибки

        # Блокировка для thread-safety
        self._lock = threading.Lock()

        # Колбэк для обновления GUI
        self._gui_callback = None

    def set_gui_callback(self, callback):
        """
        Установить колбэк для обновления GUI при новой ошибке

        Args:
            callback: функция без параметров
        """
        self._gui_callback = callback

    def add_log_line(self, log_line: str):
        """
        Добавить строку лога в буфер

        Args:
            log_line: строка из лога
        """
        with self._lock:
            # Если собираем строки после ошибки
            if self._collecting_after > 0:
                self._after_error_buffer.append(log_line)
                self._collecting_after -= 1

                # Если собрали все строки после ошибки
                if self._collecting_after == 0:
                    # Добавляем их к последней ошибке
                    if self._errors:
                        self._errors[-1]['context_after'] = list(self._after_error_buffer)
                    self._after_error_buffer.clear()

            # Добавляем в буфер контекста
            self._log_buffer.append(log_line)

    def add_error(self, log_line: str, level: str, message: str,
                  emulator_id: Optional[int] = None,
                  emulator_name: Optional[str] = None):
        """
        Добавить критическую ошибку в журнал

        Args:
            log_line: полная строка лога с ошибкой
            level: уровень (ERROR, CRITICAL)
            message: текст ошибки
            emulator_id: ID эмулятора
            emulator_name: название эмулятора
        """
        with self._lock:
            # Извлекаем эмулятор из сообщения если не передан
            if emulator_id is None or emulator_name is None:
                extracted_id, extracted_name = self._extract_emulator_info(message)
                if emulator_id is None:
                    emulator_id = extracted_id
                if emulator_name is None:
                    emulator_name = extracted_name

            error_entry = {
                'timestamp': datetime.now(),
                'level': level,
                'message': message,
                'emulator_id': emulator_id,
                'emulator_name': emulator_name or 'Unknown',
                'context_before': list(self._log_buffer),  # Копируем буфер
                'context_after': [],  # Будет заполнено позже
                'log_line': log_line
            }

            self._errors.append(error_entry)

            # Начинаем собирать строки после ошибки
            self._collecting_after = self.context_lines
            self._after_error_buffer.clear()

            # Уведомляем GUI если есть колбэк
            if self._gui_callback:
                try:
                    self._gui_callback()
                except Exception:
                    pass  # Игнорируем ошибки в колбэке

    def _extract_emulator_info(self, message: str) -> tuple:
        """
        Извлечь ID и название эмулятора из сообщения

        Args:
            message: текст сообщения

        Returns:
            (emulator_id, emulator_name)
        """
        import re

        # Паттерн: [Название эмулятора]
        name_match = re.search(r'\[([^\]]+)\]', message)
        emulator_name = name_match.group(1) if name_match else None

        # Паттерн для ID: LDPlayer-X или id:X или (id:X)
        id_patterns = [
            r'LDPlayer-(\d+)',
            r'id[:\s]+(\d+)',
            r'\(id:\s*(\d+)\)'
        ]

        emulator_id = None
        for pattern in id_patterns:
            id_match = re.search(pattern, message)
            if id_match:
                try:
                    emulator_id = int(id_match.group(1))
                    break
                except (ValueError, IndexError):
                    pass

        return emulator_id, emulator_name

    def get_errors(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Получить список ошибок

        Args:
            limit: максимальное количество ошибок (None = все)

        Returns:
            Список ошибок (от новых к старым)
        """
        with self._lock:
            errors = list(reversed(self._errors))  # От новых к старым
            if limit:
                return errors[:limit]
            return errors

    def get_error(self, index: int) -> Optional[Dict]:
        """
        Получить конкретную ошибку по индексу

        Args:
            index: индекс ошибки (0 = самая новая)

        Returns:
            Словарь с данными ошибки или None
        """
        with self._lock:
            if 0 <= index < len(self._errors):
                # Индекс с конца (0 = последняя ошибка)
                return self._errors[-(index + 1)]
            return None

    def get_error_count(self) -> int:
        """Получить количество ошибок"""
        with self._lock:
            return len(self._errors)

    def clear_errors(self):
        """Очистить все ошибки"""
        with self._lock:
            self._errors.clear()
            if self._gui_callback:
                try:
                    self._gui_callback()
                except Exception:
                    pass

    def format_error_context(self, error: Dict) -> str:
        """
        Отформатировать ошибку с контекстом для отображения

        Args:
            error: словарь с данными ошибки

        Returns:
            Отформатированный текст
        """
        lines = []

        # Заголовок
        lines.append("=" * 80)
        lines.append(f"ОШИБКА: {error['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Уровень: {error['level']}")
        if error['emulator_id']:
            lines.append(f"Эмулятор: {error['emulator_name']} (ID: {error['emulator_id']})")
        else:
            lines.append(f"Эмулятор: {error['emulator_name']}")
        lines.append("=" * 80)
        lines.append("")

        # Контекст ДО ошибки
        if error['context_before']:
            lines.append(f"--- Контекст ДО ошибки ({len(error['context_before'])} строк) ---")
            for line in error['context_before']:
                lines.append(line.rstrip())
            lines.append("")

        # Сама ошибка (выделена)
        lines.append(">>> ОШИБКА <<<")
        lines.append(error['log_line'].rstrip())
        lines.append("")

        # Контекст ПОСЛЕ ошибки
        if error['context_after']:
            lines.append(f"--- Контекст ПОСЛЕ ошибки ({len(error['context_after'])} строк) ---")
            for line in error['context_after']:
                lines.append(line.rstrip())

        return "\n".join(lines)


# Глобальный экземпляр
error_log_manager = ErrorLogManager()