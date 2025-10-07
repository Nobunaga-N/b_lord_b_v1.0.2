"""
Панель управления функциями
"""

import customtkinter as ctk
from utils.config_manager import load_config, save_config


class FunctionsPanel(ctk.CTkFrame):
    """Панель с чекбоксами функций (8 штук в 2 колонки)"""

    def __init__(self, parent):
        super().__init__(parent, corner_radius=10)

        # Данные
        self.checkbox_vars = {}  # Словарь {function_name: BooleanVar}

        # Создать UI
        self._create_ui()

        # Загрузить состояние функций
        self._load_functions()

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        # Заголовок
        header = ctk.CTkLabel(
            self,
            text="Функции (изолированное тестирование)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(anchor="w", padx=15, pady=(10, 5))

        # Контейнер для двух колонок
        columns_frame = ctk.CTkFrame(self, fg_color="transparent")
        columns_frame.pack(fill="both", expand=True, padx=15, pady=10)

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
        ]

        # Функции для правой колонки
        right_functions = [
            ("tiles", "Сбор с плиток"),
            ("prime_times", "Прайм таймы"),
            ("shield", "Щит"),
            ("mail_rewards", "Награды с почты"),
        ]

        # Создать чекбоксы для левой колонки
        for func_key, func_label in left_functions:
            self._create_checkbox(left_column, func_key, func_label)

        # Создать чекбоксы для правой колонки
        for func_key, func_label in right_functions:
            self._create_checkbox(right_column, func_key, func_label)

    def _create_checkbox(self, parent, func_key, func_label):
        """
        Создаёт чекбокс для функции

        Args:
            parent: Родительский фрейм (левая или правая колонка)
            func_key: Ключ функции (например "building")
            func_label: Отображаемое название (например "Строительство")
        """
        # Переменная для чекбокса
        var = ctk.BooleanVar(value=False)
        self.checkbox_vars[func_key] = var

        # Чекбокс
        checkbox = ctk.CTkCheckBox(
            parent,
            text=func_label,
            variable=var,
            command=self._auto_save_functions,
            font=ctk.CTkFont(size=13)
        )
        checkbox.pack(anchor="w", pady=5)

    def _load_functions(self):
        """Загружает состояние функций из gui_config.yaml"""

        # Загрузить конфиг
        gui_config = load_config("configs/gui_config.yaml")

        if not gui_config or "functions" not in gui_config:
            return

        # Установить значения чекбоксов
        functions_config = gui_config["functions"]
        for func_key, var in self.checkbox_vars.items():
            if func_key in functions_config:
                var.set(functions_config[func_key])

    def _auto_save_functions(self):
        """Автоматически сохраняет состояние функций в gui_config.yaml"""

        # Загрузить существующий конфиг (БЕЗ вывода в консоль)
        gui_config = load_config("configs/gui_config.yaml", silent=True)

        # Если конфиг пустой - создать базовую структуру
        if not gui_config:
            gui_config = {
                "emulators": {"enabled": []},
                "functions": {},
                "settings": {"max_concurrent": 3}
            }

        # Обновить состояние функций
        if "functions" not in gui_config:
            gui_config["functions"] = {}

        for func_key, var in self.checkbox_vars.items():
            gui_config["functions"][func_key] = var.get()

        # Сохранить (БЕЗ вывода в консоль)
        save_config("configs/gui_config.yaml", gui_config, silent=True)

    def get_active_functions(self):
        """
        Возвращает список активных функций

        Returns:
            list: Список ключей активных функций, например ["building", "research"]
        """
        active = []
        for func_key, var in self.checkbox_vars.items():
            if var.get():
                active.append(func_key)
        return active