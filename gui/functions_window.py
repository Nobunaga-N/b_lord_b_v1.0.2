"""
Всплывающее окно функций
"""

import customtkinter as ctk
from utils.config_manager import load_config, save_config


class FunctionsWindow(ctk.CTkToplevel):
    """Модальное окно управления функциями"""

    def __init__(self, parent):
        super().__init__(parent)

        # Настройка окна
        self.title("Функции")
        self.geometry("500x400")
        self.resizable(False, False)

        # Сделать окно модальным
        self.transient(parent)
        self.grab_set()

        # Центрировать относительно родителя
        self._center_window(parent)

        # Данные
        self.checkbox_vars = {}

        # Создать UI
        self._create_ui()

        # Загрузить состояние
        self._load_functions()

    def _center_window(self, parent):
        """Центрирует окно относительно родительского"""
        self.update_idletasks()

        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        window_width = 500
        window_height = 400

        x = parent_x + (parent_width - window_width) // 2
        y = parent_y + (parent_height - window_height) // 2

        self.geometry(f"{window_width}x{window_height}+{x}+{y}")

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        # Основной фрейм
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Заголовок
        header = ctk.CTkLabel(
            main_frame,
            text="📋 Функции (изолированное тестирование)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(pady=(0, 15))

        # Контейнер для двух колонок
        columns_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        columns_frame.pack(fill="both", expand=True)

        # Левая колонка
        left_column = ctk.CTkFrame(columns_frame, fg_color="transparent")
        left_column.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Правая колонка
        right_column = ctk.CTkFrame(columns_frame, fg_color="transparent")
        right_column.pack(side="left", fill="both", expand=True)

        # Функции для левой колонки
        left_functions = [
            ("building", "Строительство"),
            ("research", "Исследования"),
            ("wilds", "Дикие"),
            ("coop", "Кооперации"),
            ("ponds", "Пополнение прудов"),
            ("training", "Тренировка войск"),
        ]

        # Функции для правой колонки
        right_functions = [
            ("tiles", "Сбор с плиток"),
            ("prime_times", "Прайм таймы"),
            ("shield", "Щит"),
            ("mail_rewards", "Награды с почты"),
            ("feeding_zone", "Пополнение Зоны Корм."),
        ]

        # Создать чекбоксы
        for func_key, func_label in left_functions:
            self._create_checkbox(left_column, func_key, func_label)

        for func_key, func_label in right_functions:
            self._create_checkbox(right_column, func_key, func_label)

    def _create_checkbox(self, parent, func_key, func_label):
        """Создаёт чекбокс для функции"""
        var = ctk.BooleanVar(value=False)
        self.checkbox_vars[func_key] = var

        checkbox = ctk.CTkCheckBox(
            parent,
            text=func_label,
            variable=var,
            command=self._auto_save_functions,
            font=ctk.CTkFont(size=14)
        )
        checkbox.pack(anchor="w", pady=8)

    def _load_functions(self):
        """Загружает состояние функций из конфига"""
        gui_config = load_config("configs/gui_config.yaml", silent=True)

        if not gui_config or "functions" not in gui_config:
            return

        functions_config = gui_config["functions"]
        for func_key, var in self.checkbox_vars.items():
            if func_key in functions_config:
                var.set(functions_config[func_key])

    def _auto_save_functions(self):
        """Автосохранение состояния функций"""
        gui_config = load_config("configs/gui_config.yaml", silent=True)

        if not gui_config:
            gui_config = {
                "emulators": {"enabled": []},
                "functions": {},
                "settings": {"max_concurrent": 3}
            }

        if "functions" not in gui_config:
            gui_config["functions"] = {}

        for func_key, var in self.checkbox_vars.items():
            gui_config["functions"][func_key] = var.get()

        save_config("configs/gui_config.yaml", gui_config, silent=True)