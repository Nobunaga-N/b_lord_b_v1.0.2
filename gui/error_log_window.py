"""
Окно журнала критических ошибок
"""

import customtkinter as ctk
from datetime import datetime
from utils.error_log_manager import error_log_manager


class ErrorLogWindow(ctk.CTkToplevel):
    """Окно отображения журнала критических ошибок"""

    def __init__(self, parent):
        super().__init__(parent)

        # Настройка окна
        self.title("🔴 Журнал критических ошибок")
        self.geometry("1000x700")
        self.resizable(True, True)

        # Сделать окно модальным
        self.transient(parent)
        self.grab_set()

        # Центрировать относительно родителя
        self._center_window(parent)

        # Текущая выбранная ошибка
        self.selected_error_index = None

        # Создать UI
        self._create_ui()

        # Загрузить ошибки
        self._load_errors()

        # Настроить автообновление
        self._setup_auto_refresh()

    def _center_window(self, parent):
        """Центрирует окно относительно родительского"""
        self.update_idletasks()

        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        window_width = 1000
        window_height = 700

        x = parent_x + (parent_width - window_width) // 2
        y = parent_y + (parent_height - window_height) // 2

        self.geometry(f"{window_width}x{window_height}+{x}+{y}")

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        # Основной контейнер
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # === ВЕРХНЯЯ ПАНЕЛЬ: Заголовок и кнопки ===
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        # Заголовок с счетчиком
        self.header_label = ctk.CTkLabel(
            header_frame,
            text="🔴 Журнал критических ошибок (0)",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.header_label.pack(side="left")

        # Кнопки управления
        buttons_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        buttons_frame.pack(side="right")

        self.btn_refresh = ctk.CTkButton(
            buttons_frame,
            text="🔄 Обновить",
            command=self._load_errors,
            width=100
        )
        self.btn_refresh.pack(side="left", padx=5)

        self.btn_clear = ctk.CTkButton(
            buttons_frame,
            text="🗑️ Очистить",
            command=self._clear_errors,
            width=100,
            fg_color="#DC3545",
            hover_color="#C82333"
        )
        self.btn_clear.pack(side="left", padx=5)

        # === ОСНОВНАЯ ОБЛАСТЬ: Список ошибок + Детали ===
        content_frame = ctk.CTkFrame(main_frame)
        content_frame.pack(fill="both", expand=True)

        # Левая панель: список ошибок
        left_panel = ctk.CTkFrame(content_frame, width=300)
        left_panel.pack(side="left", fill="both", padx=(5, 2), pady=5)
        left_panel.pack_propagate(False)

        # Заголовок списка
        list_header = ctk.CTkLabel(
            left_panel,
            text="Список ошибок",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        list_header.pack(pady=(5, 10))

        # Прокручиваемый список ошибок
        self.error_listbox = ctk.CTkScrollableFrame(
            left_panel,
            fg_color="#2B2B2B"
        )
        self.error_listbox.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # Правая панель: детали ошибки
        right_panel = ctk.CTkFrame(content_frame)
        right_panel.pack(side="right", fill="both", expand=True, padx=(2, 5), pady=5)

        # Заголовок деталей
        details_header = ctk.CTkLabel(
            right_panel,
            text="Детали ошибки (±20 строк контекста)",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        details_header.pack(pady=(5, 10))

        # Текстовое поле для деталей
        self.details_text = ctk.CTkTextbox(
            right_panel,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="none"
        )
        self.details_text.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # Кнопка копирования
        self.btn_copy = ctk.CTkButton(
            right_panel,
            text="📋 Копировать логи",
            command=self._copy_details,
            width=150
        )
        self.btn_copy.pack(pady=5)

        # Изначально показать подсказку
        self._show_placeholder()

    def _show_placeholder(self):
        """Показать подсказку когда нет ошибок"""
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", "end")
        self.details_text.insert("1.0",
                                 "Нет критических ошибок 🎉\n\n"
                                 "Здесь будут отображаться ERROR и CRITICAL логи\n"
                                 "с контекстом ±20 строк до и после ошибки.\n\n"
                                 "Формат:\n"
                                 "- Время и дата ошибки\n"
                                 "- ID и название эмулятора\n"
                                 "- Контекст ДО ошибки\n"
                                 "- >>> ОШИБКА <<<\n"
                                 "- Контекст ПОСЛЕ ошибки"
                                 )
        self.details_text.configure(state="disabled")

    def _load_errors(self):
        """Загрузить список ошибок"""
        # Получить все ошибки
        errors = error_log_manager.get_errors()

        # Обновить счетчик в заголовке
        count = len(errors)
        self.header_label.configure(text=f"🔴 Журнал критических ошибок ({count})")

        # Очистить список
        for widget in self.error_listbox.winfo_children():
            widget.destroy()

        # Если нет ошибок
        if not errors:
            self._show_placeholder()
            return

        # Добавить ошибки в список
        for i, error in enumerate(errors):
            self._create_error_item(i, error)

    def _create_error_item(self, index: int, error: dict):
        """
        Создать элемент списка для ошибки

        Args:
            index: индекс ошибки
            error: данные ошибки
        """
        # Фрейм для ошибки
        error_frame = ctk.CTkFrame(
            self.error_listbox,
            fg_color="#3B3B3B",
            corner_radius=8
        )
        error_frame.pack(fill="x", pady=5, padx=5)

        # Контейнер для текста (левая сторона)
        text_container = ctk.CTkFrame(error_frame, fg_color="transparent")
        text_container.pack(side="left", fill="both", expand=True, padx=10, pady=8)

        # Время
        time_str = error['timestamp'].strftime('%H:%M:%S')
        date_str = error['timestamp'].strftime('%Y-%m-%d')

        time_label = ctk.CTkLabel(
            text_container,
            text=f"🕐 {time_str} ({date_str})",
            font=ctk.CTkFont(size=11),
            anchor="w"
        )
        time_label.pack(anchor="w")

        # Эмулятор
        if error['emulator_id']:
            emulator_text = f"🖥️ {error['emulator_name']} (ID: {error['emulator_id']})"
        else:
            emulator_text = f"🖥️ {error['emulator_name']}"

        emulator_label = ctk.CTkLabel(
            text_container,
            text=emulator_text,
            font=ctk.CTkFont(size=11),
            anchor="w"
        )
        emulator_label.pack(anchor="w")

        # Уровень ошибки
        level_color = "#DC3545" if error['level'] == "CRITICAL" else "#FFC107"
        level_label = ctk.CTkLabel(
            text_container,
            text=f"⚠️ {error['level']}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=level_color,
            anchor="w"
        )
        level_label.pack(anchor="w")

        # Краткое сообщение (первые 50 символов)
        short_msg = error['message'][:50] + "..." if len(error['message']) > 50 else error['message']
        msg_label = ctk.CTkLabel(
            text_container,
            text=short_msg,
            font=ctk.CTkFont(size=10),
            anchor="w"
        )
        msg_label.pack(anchor="w")

        # Кнопка "Показать"
        btn_show = ctk.CTkButton(
            error_frame,
            text="👁️",
            width=40,
            command=lambda idx=index: self._show_error_details(idx)
        )
        btn_show.pack(side="right", padx=10)

        # Клик по фрейму тоже открывает детали
        error_frame.bind("<Button-1>", lambda e, idx=index: self._show_error_details(idx))
        for widget in [text_container, time_label, emulator_label, level_label, msg_label]:
            widget.bind("<Button-1>", lambda e, idx=index: self._show_error_details(idx))

    def _show_error_details(self, index: int):
        """
        Показать детали ошибки

        Args:
            index: индекс ошибки в списке
        """
        self.selected_error_index = index

        # Получить ошибку
        error = error_log_manager.get_error(index)
        if not error:
            return

        # Отформатировать с контекстом
        formatted = error_log_manager.format_error_context(error)

        # Показать в текстовом поле
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", "end")
        self.details_text.insert("1.0", formatted)
        self.details_text.configure(state="disabled")

    def _copy_details(self):
        """Копировать детали ошибки в буфер обмена"""
        if self.selected_error_index is None:
            return

        # Получить текст из текстового поля
        text = self.details_text.get("1.0", "end-1c")

        # Копировать в буфер
        self.clipboard_clear()
        self.clipboard_append(text)

        # Временно изменить текст кнопки
        original_text = self.btn_copy.cget("text")
        self.btn_copy.configure(text="✅ Скопировано!")
        self.after(2000, lambda: self.btn_copy.configure(text=original_text))

    def _clear_errors(self):
        """Очистить все ошибки с подтверждением"""
        # Диалог подтверждения
        confirm = ctk.CTkInputDialog(
            text="Удалить все ошибки из журнала?\nВведите 'ДА' для подтверждения:",
            title="Подтверждение"
        )

        result = confirm.get_input()

        if result and result.upper() in ['ДА', 'YES']:
            error_log_manager.clear_errors()
            self._load_errors()

    def _setup_auto_refresh(self):
        """Настроить автоматическое обновление списка"""
        # Обновлять каждые 5 секунд
        self._auto_refresh()

    def _auto_refresh(self):
        """Автоматическое обновление"""
        if self.winfo_exists():
            # Сохранить текущий выбор
            old_selection = self.selected_error_index

            # Обновить список
            self._load_errors()

            # Восстановить выбор если возможно
            if old_selection is not None:
                error = error_log_manager.get_error(old_selection)
                if error:
                    self._show_error_details(old_selection)

            # Запланировать следующее обновление
            self.after(5000, self._auto_refresh)