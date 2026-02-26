"""
Панель управления эмуляторами

ОБНОВЛЕНО:
- Индикаторы статуса (🔴🟡🟢) для каждого эмулятора
- Кнопка паузы (⏸) для каждого эмулятора
- Кнопка настроек (⚙️) для каждого эмулятора
- Сохранение состояния паузы в gui_config.yaml

Версия: 2.0
"""

import customtkinter as ctk
from utils.ldconsole_manager import find_ldconsole, scan_emulators
from utils.config_manager import load_config, save_config


class EmulatorPanel(ctk.CTkFrame):
    """Панель с чекбоксами эмуляторов + индикаторы + пауза + настройки"""

    # Цвета индикаторов
    COLOR_RED = "#DC3545"      # Эмулятор выключен
    COLOR_YELLOW = "#FFC107"   # Включен, бот не на нём
    COLOR_GREEN = "#28A745"    # Бот работает на нём

    def __init__(self, parent):
        super().__init__(parent, corner_radius=10)

        # Данные
        self.emulators = []           # Список всех эмуляторов
        self.checkboxes = []          # Список виджетов чекбоксов
        self.checkbox_vars = []       # Список переменных чекбоксов
        self.ldconsole_path = None

        # Новые структуры для каждого эмулятора
        self.indicators = {}          # {emu_id: CTkLabel} — лампочки
        self.pause_buttons = {}       # {emu_id: CTkButton} — кнопки паузы
        self.pause_states = {}        # {emu_id: bool} — состояние паузы
        self.gear_buttons = {}        # {emu_id: CTkButton} — шестерёнки
        self.emulator_rows = {}       # {emu_id: CTkFrame} — строки

        # Данные от бота (обновляются извне)
        self.active_emulator_ids = set()   # Бот работает на них (зелёные)
        self.running_emulator_ids = set()  # Эмуляторы запущены (жёлтые)

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

        # Прокручиваемая область
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            height=250,
            fg_color="transparent"
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=15, pady=10)

        # Фрейм для кнопок и счётчика
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill="x", padx=15, pady=(0, 10))

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

        self.counter_label = ctk.CTkLabel(
            button_frame,
            text="Выбрано: 0/0",
            font=ctk.CTkFont(size=13)
        )
        self.counter_label.pack(side="right", padx=(5, 0))

    # ===== ЗАГРУЗКА ЭМУЛЯТОРОВ =====

    def _load_emulators(self):
        """Загружает список эмуляторов"""

        self.ldconsole_path = find_ldconsole()

        if not self.ldconsole_path:
            error_label = ctk.CTkLabel(
                self.scroll_frame,
                text="❌ Ошибка: ldconsole.exe не найден на дисках C:\\, D:\\, E:\\",
                text_color="#f44336",
                font=ctk.CTkFont(size=13)
            )
            error_label.pack(pady=20)
            return

        # Загрузить из конфига или сканировать
        emulators_config = load_config("configs/emulators.yaml")
        if emulators_config and "emulators" in emulators_config and emulators_config["emulators"]:
            self.emulators = emulators_config["emulators"]
        else:
            self.emulators = scan_emulators(self.ldconsole_path)
            if self.emulators:
                save_config("configs/emulators.yaml", {"emulators": self.emulators})

        # Загрузить gui_config
        gui_config = load_config("configs/gui_config.yaml")
        enabled_ids = gui_config.get("emulators", {}).get("enabled", []) if gui_config else []

        # Загрузить состояния паузы
        self._load_pause_states(gui_config)

        # Отобразить
        self._display_emulators(enabled_ids)

    def _load_pause_states(self, gui_config=None):
        """Загружает состояния паузы из конфига"""
        if gui_config is None:
            gui_config = load_config("configs/gui_config.yaml", silent=True) or {}

        emu_settings = gui_config.get("emulator_settings", {})
        self.pause_states = {}
        for emu in self.emulators:
            emu_id = emu["id"]
            settings = emu_settings.get(str(emu_id), emu_settings.get(emu_id, {}))
            self.pause_states[emu_id] = settings.get("paused", False)

    # ===== ОТОБРАЖЕНИЕ ЭМУЛЯТОРОВ =====

    def _display_emulators(self, enabled_ids):
        """Отображает строки эмуляторов: [🔴] [☑️ name] [⏸] [⚙️]"""

        # Очистить
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        self.checkboxes.clear()
        self.checkbox_vars.clear()
        self.indicators.clear()
        self.pause_buttons.clear()
        self.gear_buttons.clear()
        self.emulator_rows.clear()

        if not self.emulators:
            no_emu_label = ctk.CTkLabel(
                self.scroll_frame,
                text="Эмуляторы не найдены",
                text_color="#9e9e9e",
                font=ctk.CTkFont(size=13)
            )
            no_emu_label.pack(pady=20)
            self._update_counter()
            return

        for emu in self.emulators:
            emu_id = emu["id"]

            # Строка-контейнер
            row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row.pack(fill="x", pady=3, padx=5)
            self.emulator_rows[emu_id] = row

            # 1) Индикатор (лампочка)
            indicator = ctk.CTkLabel(
                row,
                text="●",
                font=ctk.CTkFont(size=16),
                text_color=self.COLOR_RED,
                width=20
            )
            indicator.pack(side="left", padx=(0, 5))
            self.indicators[emu_id] = indicator

            # 2) Чекбокс
            var = ctk.BooleanVar(value=emu_id in enabled_ids)
            self.checkbox_vars.append(var)

            text = f"{emu['name']} (id:{emu_id})"
            checkbox = ctk.CTkCheckBox(
                row,
                text=text,
                variable=var,
                command=self._update_counter,
                font=ctk.CTkFont(size=13),
                width=220
            )
            checkbox.pack(side="left", padx=(0, 5))
            self.checkboxes.append(checkbox)

            # 3) Кнопка паузы
            is_paused = self.pause_states.get(emu_id, False)
            pause_text = "▶" if is_paused else "⏸"
            pause_color = "#FFC107" if is_paused else "#6C757D"

            pause_btn = ctk.CTkButton(
                row,
                text=pause_text,
                width=32,
                height=28,
                font=ctk.CTkFont(size=14),
                fg_color=pause_color,
                hover_color="#5A6268",
                command=lambda eid=emu_id: self._on_pause_click(eid)
            )
            pause_btn.pack(side="left", padx=2)
            self.pause_buttons[emu_id] = pause_btn

            # 4) Кнопка настроек (шестерёнка)
            gear_btn = ctk.CTkButton(
                row,
                text="⚙",
                width=32,
                height=28,
                font=ctk.CTkFont(size=14),
                fg_color="#495057",
                hover_color="#5A6268",
                command=lambda eid=emu_id, en=emu['name']: self._on_gear_click(eid, en)
            )
            gear_btn.pack(side="left", padx=2)
            self.gear_buttons[emu_id] = gear_btn

        self._update_counter()

    # ===== ПАУЗА =====

    def _on_pause_click(self, emulator_id):
        """Переключает паузу для эмулятора"""
        current = self.pause_states.get(emulator_id, False)
        new_state = not current
        self.pause_states[emulator_id] = new_state

        # Обновить кнопку
        btn = self.pause_buttons.get(emulator_id)
        if btn:
            if new_state:
                btn.configure(text="▶", fg_color="#FFC107")
            else:
                btn.configure(text="⏸", fg_color="#6C757D")

        # Сохранить
        self._save_pause_state(emulator_id, new_state)

    def _save_pause_state(self, emulator_id, paused):
        """Сохраняет состояние паузы в gui_config.yaml"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}

        if "emulator_settings" not in gui_config:
            gui_config["emulator_settings"] = {}

        emu_key = str(emulator_id)
        if emu_key not in gui_config["emulator_settings"]:
            gui_config["emulator_settings"][emu_key] = {}

        gui_config["emulator_settings"][emu_key]["paused"] = paused
        save_config("configs/gui_config.yaml", gui_config, silent=True)

    def is_paused(self, emulator_id):
        """Проверяет на паузе ли эмулятор"""
        return self.pause_states.get(emulator_id, False)

    def get_paused_ids(self):
        """Возвращает список ID запауженных эмуляторов"""
        return [eid for eid, paused in self.pause_states.items() if paused]

    # ===== ШЕСТЕРЁНКА =====

    def _on_gear_click(self, emulator_id, emulator_name):
        """Открывает окно настроек эмулятора"""
        from gui.emulator_settings_window import EmulatorSettingsWindow
        EmulatorSettingsWindow(self, emulator_id, emulator_name)

    # ===== ИНДИКАТОРЫ =====

    def update_indicators(self, active_ids=None, running_ids=None):
        """
        Обновляет индикаторы всех эмуляторов

        Args:
            active_ids: set — эмуляторы, на которых бот работает (🟢)
            running_ids: set — эмуляторы, которые запущены (🟡)
        """
        if active_ids is not None:
            self.active_emulator_ids = set(active_ids)
        if running_ids is not None:
            self.running_emulator_ids = set(running_ids)

        for emu in self.emulators:
            emu_id = emu["id"]
            indicator = self.indicators.get(emu_id)
            if not indicator:
                continue

            if emu_id in self.active_emulator_ids:
                indicator.configure(text_color=self.COLOR_GREEN)
            elif emu_id in self.running_emulator_ids:
                indicator.configure(text_color=self.COLOR_YELLOW)
            else:
                indicator.configure(text_color=self.COLOR_RED)

    # ===== СТАНДАРТНЫЕ МЕТОДЫ (без изменений в логике) =====

    def _refresh_list(self):
        """Обновляет список эмуляторов"""
        if not self.ldconsole_path:
            return
        current_selected = self.get_selected_emulator_ids()
        self.emulators = scan_emulators(self.ldconsole_path)
        if self.emulators:
            save_config("configs/emulators.yaml", {"emulators": self.emulators})
        gui_config = load_config("configs/gui_config.yaml", silent=True)
        self._load_pause_states(gui_config)
        self._display_emulators(current_selected)

    def _select_all(self):
        for var in self.checkbox_vars:
            var.set(True)
        self._update_counter()

    def _select_none(self):
        for var in self.checkbox_vars:
            var.set(False)
        self._update_counter()

    def _update_counter(self):
        selected = sum(1 for var in self.checkbox_vars if var.get())
        total = len(self.checkbox_vars)
        self.counter_label.configure(text=f"Выбрано: {selected}/{total}")
        self._auto_save_selection()

    def get_selected_emulator_ids(self):
        selected = []
        for i, var in enumerate(self.checkbox_vars):
            if var.get() and i < len(self.emulators):
                selected.append(self.emulators[i]["id"])
        return selected

    def _auto_save_selection(self):
        selected_ids = self.get_selected_emulator_ids()
        gui_config = load_config("configs/gui_config.yaml", silent=True)
        if not gui_config:
            gui_config = {
                "emulators": {"enabled": []},
                "functions": {
                    "building": False, "research": False, "wilds": False,
                    "coop": False, "tiles": False, "prime_times": False,
                    "shield": False, "mail_rewards": False
                },
                "settings": {"max_concurrent": 3}
            }
        if "emulators" not in gui_config:
            gui_config["emulators"] = {}
        gui_config["emulators"]["enabled"] = selected_ids
        save_config("configs/gui_config.yaml", gui_config, silent=True)