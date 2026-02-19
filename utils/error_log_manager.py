"""
Менеджер журнала критических ошибок
Собирает ERROR и CRITICAL логи с контекстом для анализа

ОБНОВЛЕНО:
- Thread-safe флаг вместо прямого GUI callback
- Персистентное хранение в JSON файл (переживает перезапуск)
"""

import os
import json
import threading
from datetime import datetime
from typing import List, Dict, Optional
from collections import deque


# Путь к файлу журнала ошибок
ERROR_JOURNAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'logs', 'error_journal.json'
)


class ErrorLogManager:
    """
    Менеджер для сбора критических ошибок с контекстом

    Функционал:
    - Автоматический сбор ERROR/CRITICAL из логов
    - Хранение ±20 строк контекста вокруг ошибки
    - Привязка к ID и названию эмулятора
    - Thread-safe операции
    - Персистентное хранение в JSON (переживает перезапуск)
    - Thread-safe уведомление GUI через флаг
    """

    def __init__(self, context_lines: int = 20):
        self.context_lines = context_lines

        # Хранилище ошибок
        self._errors: List[Dict] = []

        # Буфер последних строк лога (для контекста)
        self._log_buffer = deque(maxlen=context_lines)

        # Буфер для строк после ошибки
        self._after_error_buffer = []
        self._collecting_after = 0

        # Блокировка для thread-safety
        self._lock = threading.Lock()

        # Thread-safe флаг для GUI
        self._has_new_errors = False

        # Загрузить ошибки из файла при старте
        self._load_from_file()

    # ===== ПЕРСИСТЕНТНОЕ ХРАНЕНИЕ =====

    def _load_from_file(self):
        """Загрузить ошибки из JSON файла при старте"""
        try:
            if os.path.exists(ERROR_JOURNAL_PATH):
                with open(ERROR_JOURNAL_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                for entry in data:
                    # Восстанавливаем datetime из строки
                    entry['timestamp'] = datetime.fromisoformat(
                        entry['timestamp']
                    )
                    self._errors.append(entry)

                if self._errors:
                    self._has_new_errors = True

        except Exception as e:
            # Не ломаем запуск из-за битого файла
            print(f"⚠️ Не удалось загрузить журнал ошибок: {e}")
            self._errors = []

    def _save_to_file(self):
        """
        Сохранить ошибки в JSON файл

        Вызывается ВНУТРИ lock (из add_error и clear_errors).
        """
        try:
            # Создать директорию если нет
            os.makedirs(os.path.dirname(ERROR_JOURNAL_PATH), exist_ok=True)

            # Конвертируем для JSON
            data = []
            for entry in self._errors:
                json_entry = dict(entry)
                json_entry['timestamp'] = entry['timestamp'].isoformat()
                data.append(json_entry)

            with open(ERROR_JOURNAL_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception:
            pass  # Не ломаем работу из-за ошибки сохранения

    # ===== GUI ВЗАИМОДЕЙСТВИЕ =====

    def check_new_errors(self) -> bool:
        """
        Проверить есть ли новые ошибки (вызывается из GUI потока)

        Возвращает True и сбрасывает флаг.
        """
        with self._lock:
            if self._has_new_errors:
                self._has_new_errors = False
                return True
            return False

    # ===== ОСНОВНЫЕ МЕТОДЫ =====

    def add_log_line(self, log_line: str):
        """Добавить строку лога в буфер"""
        with self._lock:
            if self._collecting_after > 0:
                self._after_error_buffer.append(log_line)
                self._collecting_after -= 1

                if self._collecting_after == 0:
                    if self._errors:
                        self._errors[-1]['context_after'] = list(
                            self._after_error_buffer
                        )
                        # Сохранить обновлённый контекст
                        self._save_to_file()
                    self._after_error_buffer.clear()

            self._log_buffer.append(log_line)

    def add_error(self, log_line: str, level: str, message: str,
                  emulator_id: Optional[int] = None,
                  emulator_name: Optional[str] = None):
        """Добавить критическую ошибку в журнал"""
        with self._lock:
            if emulator_id is None or emulator_name is None:
                extracted_id, extracted_name = (
                    self._extract_emulator_info(message)
                )
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
                'context_before': list(self._log_buffer),
                'context_after': [],
                'log_line': log_line
            }

            self._errors.append(error_entry)

            # Начинаем собирать строки после ошибки
            self._collecting_after = self.context_lines
            self._after_error_buffer.clear()

            # Флаг для GUI
            self._has_new_errors = True

            # Сохранить в файл
            self._save_to_file()

    def _extract_emulator_info(self, message: str) -> tuple:
        """Извлечь ID и название эмулятора из сообщения"""
        import re

        name_match = re.search(r'\[([^\]]+)\]', message)
        emulator_name = name_match.group(1) if name_match else None

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
        """Получить список ошибок (от новых к старым)"""
        with self._lock:
            errors = list(reversed(self._errors))
            if limit:
                return errors[:limit]
            return errors

    def get_error(self, index: int) -> Optional[Dict]:
        """Получить конкретную ошибку по индексу (0 = самая новая)"""
        with self._lock:
            if 0 <= index < len(self._errors):
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
            self._has_new_errors = True
            self._save_to_file()

    def format_error_context(self, error: Dict) -> str:
        """Отформатировать ошибку с контекстом для отображения"""
        lines = []

        lines.append("=" * 80)
        lines.append(
            f"ОШИБКА: {error['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}"
        )
        lines.append(f"Уровень: {error['level']}")
        if error['emulator_id']:
            lines.append(
                f"Эмулятор: {error['emulator_name']} "
                f"(ID: {error['emulator_id']})"
            )
        else:
            lines.append(f"Эмулятор: {error['emulator_name']}")
        lines.append("=" * 80)
        lines.append("")

        if error['context_before']:
            lines.append(
                f"--- Контекст ДО ошибки "
                f"({len(error['context_before'])} строк) ---"
            )
            for line in error['context_before']:
                lines.append(line.rstrip())
            lines.append("")

        lines.append(">>> ОШИБКА <<<")
        lines.append(error['log_line'].rstrip())
        lines.append("")

        if error['context_after']:
            lines.append(
                f"--- Контекст ПОСЛЕ ошибки "
                f"({len(error['context_after'])} строк) ---"
            )
            for line in error['context_after']:
                lines.append(line.rstrip())

        return "\n".join(lines)


# Глобальный экземпляр
error_log_manager = ErrorLogManager()