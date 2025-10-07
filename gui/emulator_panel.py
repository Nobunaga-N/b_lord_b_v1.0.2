"""
Панель управления эмуляторами
"""

import customtkinter as ctk
from utils.ldconsole_manager import find_ldconsole, scan_emulators
from utils.config_manager import load_config, save_config


class EmulatorPanel(ctk.CTkFrame):
    """Панель с чекбоксами эмуляторов"""

    def __init__(self, parent):
        super().__init__(parent, corner_radius=10)

        # Данные
        self.emulators = []  # Список всех эмуляторов
        self.checkboxes = []  # Список виджетов чекбоксов
        self.checkbox_vars = []  # Список переменных чекбоксов
        self.ldconsole_path = None

        # Создать UI
        self._create_ui()

        # Загрузить эмуляторы
        self._load_emulators()

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        # Заголовок
        header = ctk.CTkLabel(
            self,
            text="Эмуляторы",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(anchor="w", padx=15, pady=(10, 5))

        # Прокручиваемая область для чекбоксов
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            height=300,
            fg_color="transparent"
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=15, pady=10)

        # Фрейм для кнопок и счётчика
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill="x", padx=15, pady=(0, 10))

        # Кнопки управления
        btn_refresh = ctk.CTkButton(
            button_frame,
            text="Обновить список",
            width=140,
            command=self._refresh_list
        )
        btn_refresh.pack(side="left", padx=(0, 5))

        btn_all = ctk.CTkButton(
            button_frame,
            text="Все",
            width=80,
            command=self._select_all
        )
        btn_all.pack(side="left", padx=5)

        btn_none = ctk.CTkButton(
            button_frame,
            text="Ничего",
            width=80,
            command=self._select_none
        )
        btn_none.pack(side="left", padx=5)

        # Счётчик выбранных
        self.counter_label = ctk.CTkLabel(
            button_frame,
            text="Выбрано: 0/0",
            font=ctk.CTkFont(size=13)
        )
        self.counter_label.pack(side="right", padx=(5, 0))

    def _load_emulators(self):
        """Загружает список эмуляторов (автосканирование при первом запуске)"""

        # Найти ldconsole.exe
        self.ldconsole_path = find_ldconsole()

        if not self.ldconsole_path:
            # Показать ошибку в панели
            error_label = ctk.CTkLabel(
                self.scroll_frame,
                text="❌ Ошибка: ldconsole.exe не найден на дисках C:\\, D:\\, E:\\",
                text_color="#f44336",
                font=ctk.CTkFont(size=13)
            )
            error_label.pack(pady=20)
            return

        # Загрузить список эмуляторов из файла
        emulators_config = load_config("configs/emulators.yaml")

        if emulators_config and "emulators" in emulators_config and emulators_config["emulators"]:
            # Файл существует и содержит эмуляторы
            self.emulators = emulators_config["emulators"]
            print(f"[INFO] Загружено {len(self.emulators)} эмуляторов из конфига")
        else:
            # Файл пустой или не существует → автосканирование
            print("[INFO] Файл эмуляторов пуст, запуск автосканирования...")
            self.emulators = scan_emulators(self.ldconsole_path)

            # Сохранить результат
            if self.emulators:
                save_config("configs/emulators.yaml", {"emulators": self.emulators})

        # Загрузить выбранные эмуляторы из gui_config.yaml
        gui_config = load_config("configs/gui_config.yaml")
        enabled_ids = gui_config.get("emulators", {}).get("enabled", []) if gui_config else []

        # Отобразить чекбоксы
        self._display_emulators(enabled_ids)

    def _display_emulators(self, enabled_ids):
        """
        Отображает чекбоксы с эмуляторами

        Args:
            enabled_ids: Список ID включенных эмуляторов
        """

        # Очистить старые чекбоксы
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        self.checkboxes.clear()
        self.checkbox_vars.clear()

        if not self.emulators:
            # Эмуляторы не найдены
            no_emu_label = ctk.CTkLabel(
                self.scroll_frame,
                text="Эмуляторы не найдены",
                text_color="#9e9e9e",
                font=ctk.CTkFont(size=13)
            )
            no_emu_label.pack(pady=20)
            self._update_counter()
            return

        # Создать чекбоксы
        for emu in self.emulators:
            # Переменная для чекбокса
            var = ctk.BooleanVar(value=emu["id"] in enabled_ids)
            self.checkbox_vars.append(var)

            # Текст: "LDPlayer (id:0, port:5554)"
            text = f"{emu['name']} (id:{emu['id']}, port:{emu['port']})"

            # Чекбокс
            checkbox = ctk.CTkCheckBox(
                self.scroll_frame,
                text=text,
                variable=var,
                command=self._update_counter,
                font=ctk.CTkFont(size=13)
            )
            checkbox.pack(anchor="w", pady=5, padx=10)
            self.checkboxes.append(checkbox)

        # Обновить счётчик
        self._update_counter()

    def _refresh_list(self):
        """Обновляет список эмуляторов (кнопка 'Обновить список')"""

        if not self.ldconsole_path:
            print("[ERROR] ldconsole.exe не найден, обновление невозможно")
            return

        # Сохранить текущий выбор
        current_selected = self.get_selected_emulator_ids()

        # Сканировать эмуляторы
        print("[INFO] Сканирование эмуляторов...")
        self.emulators = scan_emulators(self.ldconsole_path)

        # Сохранить в файл
        if self.emulators:
            save_config("configs/emulators.yaml", {"emulators": self.emulators})

        # Перерисовать чекбоксы (сохранив выбор)
        self._display_emulators(current_selected)

    def _select_all(self):
        """Выбирает все эмуляторы"""
        for var in self.checkbox_vars:
            var.set(True)
        self._update_counter()

    def _select_none(self):
        """Снимает выбор со всех эмуляторов"""
        for var in self.checkbox_vars:
            var.set(False)
        self._update_counter()

    def _update_counter(self):
        """Обновляет счётчик выбранных эмуляторов и автосохраняет выбор"""
        selected = sum(1 for var in self.checkbox_vars if var.get())
        total = len(self.checkbox_vars)
        self.counter_label.configure(text=f"Выбрано: {selected}/{total}")

        # Автосохранение выбора в gui_config.yaml
        self._auto_save_selection()

    def get_selected_emulator_ids(self):
        """
        Возвращает список ID выбранных эмуляторов

        Returns:
            list: [0, 1, 7, ...]
        """
        selected = []
        for i, var in enumerate(self.checkbox_vars):
            if var.get() and i < len(self.emulators):
                selected.append(self.emulators[i]["id"])
        return selected

    def _auto_save_selection(self):
        """Автоматически сохраняет выбранные эмуляторы в gui_config.yaml"""

        # Получить текущий выбор
        selected_ids = self.get_selected_emulator_ids()

        # Загрузить существующий конфиг (если есть)
        gui_config = load_config("configs/gui_config.yaml")

        # Если конфиг пустой - создать базовую структуру
        if not gui_config:
            gui_config = {
                "emulators": {"enabled": []},
                "functions": {
                    "building": False,
                    "research": False,
                    "wilds": False,
                    "coop": False,
                    "tiles": False,
                    "prime_times": False,
                    "shield": False,
                    "mail_rewards": False
                },
                "settings": {"max_concurrent": 3}
            }

        # Обновить выбранные эмуляторы
        if "emulators" not in gui_config:
            gui_config["emulators"] = {}
        gui_config["emulators"]["enabled"] = selected_ids

        # Сохранить
        save_config("configs/gui_config.yaml", gui_config)