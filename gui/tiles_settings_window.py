"""
Окно настройки плиток для конкретного эмулятора

Настройки:
- Чекбоксы ресурсов: Яблоки, Листья, Грунт, Песок (все вкл по умолчанию)
- Мин. уровень плитки (default: 4, range: 1-18)
- Макс. уровень плитки (default: 7, range: 1-18)
- Валидация: мин ≤ макс

Сохраняется в gui_config.yaml:
  emulator_settings:
    '{emu_id}':
      tiles:
        resources:
          apples: true
          leaves: true
          soil: true
          sand: true
        min_level: 4
        max_level: 7

Версия: 1.0
Дата создания: 2025-03-17
"""

import customtkinter as ctk
from utils.config_manager import load_config, save_config


# Ресурсы для плиток (без мёда — его нельзя собирать на плитках)
DEFAULT_TILE_RESOURCES = {
    "apples": {"label": "🍎 Яблоки", "enabled": True},
    "leaves": {"label": "🌿 Листья", "enabled": True},
    "soil":   {"label": "🟤 Грунт",  "enabled": True},
    "sand":   {"label": "🟡 Песок",  "enabled": True},
}

# Уровни плиток по умолчанию
DEFAULT_MIN_LEVEL = 4
DEFAULT_MAX_LEVEL = 7
LEVEL_RANGE = (1, 18)


class TilesSettingsWindow(ctk.CTkToplevel):
    """Окно настройки плиток для конкретного эмулятора"""

    def __init__(self, parent, emulator_id, emulator_name):
        super().__init__(parent)

        self.emulator_id = emulator_id
        self.emulator_name = emulator_name

        # Настройки окна
        self.title(f"Плитки — {emulator_name}")
        self.resizable(False, False)
        self.grab_set()

        # Переменные
        self.resource_vars = {}   # {resource_key: BooleanVar}
        self.min_level_var = ctk.StringVar(value=str(DEFAULT_MIN_LEVEL))
        self.max_level_var = ctk.StringVar(value=str(DEFAULT_MAX_LEVEL))

        # Размер и позиция
        w, h = 320, 470
        self._center_window(parent, w, h)

        # UI
        self._create_ui()

        # Загрузить данные
        self._load_settings()

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
            text=f"🗺 Плитки — {self.emulator_name}",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        header.pack(pady=(15, 5))

        hint = ctk.CTkLabel(
            self,
            text="Бот будет отправлять отряды только\n"
                 "на включённые ресурсы",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E",
            justify="center"
        )
        hint.pack(pady=(0, 15))

        # === ЧЕКБОКСЫ РЕСУРСОВ ===
        cb_frame = ctk.CTkFrame(self, fg_color="transparent")
        cb_frame.pack(fill="x", padx=40, pady=5)

        for res_key, defaults in DEFAULT_TILE_RESOURCES.items():
            var = ctk.BooleanVar(value=defaults["enabled"])
            self.resource_vars[res_key] = var

            cb = ctk.CTkCheckBox(
                cb_frame,
                text=defaults["label"],
                variable=var,
                font=ctk.CTkFont(size=13),
                command=self._on_change
            )
            cb.pack(anchor="w", pady=4)

        # === УРОВНИ ПЛИТОК ===
        levels_frame = ctk.CTkFrame(self, fg_color="transparent")
        levels_frame.pack(fill="x", padx=40, pady=(15, 5))

        ctk.CTkLabel(
            levels_frame,
            text="📊 Уровень плиток",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", pady=(0, 8))

        # Мин. уровень
        min_row = ctk.CTkFrame(levels_frame, fg_color="transparent")
        min_row.pack(fill="x", pady=2)

        ctk.CTkLabel(
            min_row, text="Мин:",
            font=ctk.CTkFont(size=12), width=40
        ).pack(side="left")

        min_entry = ctk.CTkEntry(
            min_row, textvariable=self.min_level_var,
            width=60, height=28, font=ctk.CTkFont(size=12),
            justify="center"
        )
        min_entry.pack(side="left", padx=(5, 0))
        min_entry.bind("<FocusOut>", lambda e: self._validate_levels())

        # Макс. уровень
        max_row = ctk.CTkFrame(levels_frame, fg_color="transparent")
        max_row.pack(fill="x", pady=2)

        ctk.CTkLabel(
            max_row, text="Макс:",
            font=ctk.CTkFont(size=12), width=40
        ).pack(side="left")

        max_entry = ctk.CTkEntry(
            max_row, textvariable=self.max_level_var,
            width=60, height=28, font=ctk.CTkFont(size=12),
            justify="center"
        )
        max_entry.pack(side="left", padx=(5, 0))
        max_entry.bind("<FocusOut>", lambda e: self._validate_levels())

        # Подсказка
        ctk.CTkLabel(
            self,
            text="ℹ️ Бот начинает поиск с мин. уровня\n"
                 "и повышает до макс., пока не найдёт",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E",
            justify="center"
        ).pack(pady=(10, 5))

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

    def _on_change(self):
        """Автосохранение при переключении чекбокса"""
        self._auto_save()

    def _validate_levels(self):
        """Валидирует поля уровней: мин ≤ макс, в пределах 1-18"""
        try:
            min_val = int(self.min_level_var.get())
        except (ValueError, TypeError):
            min_val = DEFAULT_MIN_LEVEL

        try:
            max_val = int(self.max_level_var.get())
        except (ValueError, TypeError):
            max_val = DEFAULT_MAX_LEVEL

        # Ограничить диапазон
        min_val = max(LEVEL_RANGE[0], min(LEVEL_RANGE[1], min_val))
        max_val = max(LEVEL_RANGE[0], min(LEVEL_RANGE[1], max_val))

        # мин не больше макс
        if min_val > max_val:
            min_val = max_val

        self.min_level_var.set(str(min_val))
        self.max_level_var.set(str(max_val))
        self._auto_save()

    def _load_settings(self):
        """Загружает настройки плиток из конфига"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(self.emulator_id)
        settings = emu_settings.get(emu_key, {})
        tiles = settings.get("tiles", {})
        resources = tiles.get("resources", {})

        for res_key, defaults in DEFAULT_TILE_RESOURCES.items():
            saved_value = resources.get(res_key, defaults["enabled"])
            self.resource_vars[res_key].set(saved_value)

        self.min_level_var.set(
            str(tiles.get("min_level", DEFAULT_MIN_LEVEL))
        )
        self.max_level_var.set(
            str(tiles.get("max_level", DEFAULT_MAX_LEVEL))
        )

    def _auto_save(self):
        """Сохраняет настройки плиток в gui_config.yaml"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}

        if "emulator_settings" not in gui_config:
            gui_config["emulator_settings"] = {}

        emu_key = str(self.emulator_id)
        if emu_key not in gui_config["emulator_settings"]:
            gui_config["emulator_settings"][emu_key] = {}

        # Ресурсы
        resources_data = {}
        for res_key in DEFAULT_TILE_RESOURCES:
            resources_data[res_key] = self.resource_vars[res_key].get()

        # Уровни
        try:
            min_level = int(self.min_level_var.get())
        except (ValueError, TypeError):
            min_level = DEFAULT_MIN_LEVEL

        try:
            max_level = int(self.max_level_var.get())
        except (ValueError, TypeError):
            max_level = DEFAULT_MAX_LEVEL

        gui_config["emulator_settings"][emu_key]["tiles"] = {
            "resources": resources_data,
            "min_level": min_level,
            "max_level": max_level,
        }

        save_config("configs/gui_config.yaml", gui_config, silent=True)

    def _save_and_close(self):
        """Сохраняет и закрывает окно"""
        self._validate_levels()
        self._auto_save()
        self.destroy()