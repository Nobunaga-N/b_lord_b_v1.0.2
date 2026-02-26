"""
Окно настройки Вожаков (Отрядов) для конкретного эмулятора

4 отряда:
- Особый Отряд (включён по умолчанию)
- Отряд I (включён по умолчанию)
- Отряд II (выключен, открывается на 13 ур Лорда)
- Отряд III (выключен, открывается на 18 ур Лорда)

Каждый отряд имеет поле для ввода уровня диких (1-15).

Версия: 1.0
"""

import customtkinter as ctk
from utils.config_manager import load_config, save_config


# Конфигурация отрядов по умолчанию
DEFAULT_SQUADS = {
    "special": {"label": "Особый Отряд", "enabled": True, "wild_level": 1},
    "squad_1": {"label": "Отряд I", "enabled": True, "wild_level": 1},
    "squad_2": {"label": "Отряд II", "enabled": False, "wild_level": 1},
    "squad_3": {"label": "Отряд III", "enabled": False, "wild_level": 1},
}


class LeadersWindow(ctk.CTkToplevel):
    """Окно настройки отрядов вожаков"""

    def __init__(self, parent, emulator_id, emulator_name):
        super().__init__(parent)

        self.emulator_id = emulator_id
        self.emulator_name = emulator_name

        # Настройки окна
        self.title(f"Вожаки — {emulator_name}")
        self.resizable(False, False)
        self.grab_set()

        # Переменные
        self.squad_vars = {}    # {squad_key: BooleanVar}
        self.level_vars = {}    # {squad_key: StringVar}
        self.level_entries = {} # {squad_key: CTkEntry}

        # Размер и позиция
        w, h = 400, 380
        self._center_window(parent, w, h)

        # UI
        self._create_ui()

        # Загрузить данные
        self._load_squad_settings()

    def _center_window(self, parent, w, h):
        self.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _create_ui(self):
        """Создаёт интерфейс"""

        # Заголовок
        header = ctk.CTkLabel(
            self,
            text=f"🐾 Отряды вожаков — {self.emulator_name}",
            font=ctk.CTkFont(size=15, weight="bold")
        )
        header.pack(pady=(15, 5))

        hint = ctk.CTkLabel(
            self,
            text="Уровень диких: число от 1 до 15",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E"
        )
        hint.pack(pady=(0, 10))

        # Таблица отрядов
        table = ctk.CTkFrame(self, fg_color="transparent")
        table.pack(fill="x", padx=20, pady=5)

        # Заголовки столбцов
        header_row = ctk.CTkFrame(table, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 5))

        ctk.CTkLabel(
            header_row, text="Вкл.", width=50,
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left")
        ctk.CTkLabel(
            header_row, text="Отряд", width=180,
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
        ).pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            header_row, text="Ур. диких", width=80,
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left", padx=(10, 0))

        # Строки отрядов
        for squad_key, defaults in DEFAULT_SQUADS.items():
            row = ctk.CTkFrame(table, fg_color="transparent")
            row.pack(fill="x", pady=4)

            # Чекбокс включения
            var = ctk.BooleanVar(value=defaults["enabled"])
            self.squad_vars[squad_key] = var

            cb = ctk.CTkCheckBox(
                row, text="", variable=var,
                width=30,
                command=self._on_change
            )
            cb.pack(side="left")

            # Название отряда
            ctk.CTkLabel(
                row, text=defaults["label"],
                font=ctk.CTkFont(size=13), anchor="w", width=180
            ).pack(side="left", padx=(10, 0))

            # Поле ввода уровня
            level_var = ctk.StringVar(value=str(defaults["wild_level"]))
            self.level_vars[squad_key] = level_var

            entry = ctk.CTkEntry(
                row, textvariable=level_var,
                width=60, height=28,
                font=ctk.CTkFont(size=13),
                justify="center"
            )
            entry.pack(side="left", padx=(10, 0))
            self.level_entries[squad_key] = entry

            # Валидация при потере фокуса
            entry.bind("<FocusOut>", lambda e, k=squad_key: self._validate_level(k))
            entry.bind("<Return>", lambda e, k=squad_key: self._validate_level(k))

        # Подсказки
        notes_frame = ctk.CTkFrame(self, fg_color="transparent")
        notes_frame.pack(fill="x", padx=20, pady=(15, 5))

        ctk.CTkLabel(
            notes_frame,
            text="ℹ️ Отряд II открывается на 13 ур. Лорда\n"
                 "ℹ️ Отряд III открывается на 18 ур. Лорда",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E",
            justify="left"
        ).pack(anchor="w")

        # Кнопка сохранить
        btn_save = ctk.CTkButton(
            self,
            text="💾 Сохранить",
            width=150,
            height=35,
            fg_color="#28A745",
            hover_color="#218838",
            command=self._save_and_close
        )
        btn_save.pack(pady=(15, 15))

    # ===== ЛОГИКА =====

    def _validate_level(self, squad_key):
        """Валидирует поле уровня (1-15)"""
        var = self.level_vars[squad_key]
        try:
            val = int(var.get())
            val = max(1, min(15, val))
            var.set(str(val))
        except (ValueError, TypeError):
            var.set("1")
        self._auto_save()

    def _on_change(self):
        """Автосохранение при переключении чекбокса"""
        self._auto_save()

    def _load_squad_settings(self):
        """Загружает настройки отрядов из конфига"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(self.emulator_id)
        settings = emu_settings.get(emu_key, {})
        squads = settings.get("squads", {})

        for squad_key, defaults in DEFAULT_SQUADS.items():
            saved = squads.get(squad_key, {})
            self.squad_vars[squad_key].set(
                saved.get("enabled", defaults["enabled"])
            )
            level = saved.get("wild_level", defaults["wild_level"])
            level = max(1, min(15, level))
            self.level_vars[squad_key].set(str(level))

    def _auto_save(self):
        """Сохраняет настройки отрядов в gui_config.yaml"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}

        if "emulator_settings" not in gui_config:
            gui_config["emulator_settings"] = {}

        emu_key = str(self.emulator_id)
        if emu_key not in gui_config["emulator_settings"]:
            gui_config["emulator_settings"][emu_key] = {}

        squads_data = {}
        for squad_key in DEFAULT_SQUADS:
            try:
                level = int(self.level_vars[squad_key].get())
                level = max(1, min(15, level))
            except (ValueError, TypeError):
                level = 1

            squads_data[squad_key] = {
                "enabled": self.squad_vars[squad_key].get(),
                "wild_level": level
            }

        gui_config["emulator_settings"][emu_key]["squads"] = squads_data
        save_config("configs/gui_config.yaml", gui_config, silent=True)

    def _save_and_close(self):
        """Сохраняет и закрывает окно"""
        # Валидировать все поля
        for squad_key in DEFAULT_SQUADS:
            self._validate_level(squad_key)
        self._auto_save()
        self.destroy()