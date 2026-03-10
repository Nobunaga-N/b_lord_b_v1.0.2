"""
Окно настройки ресурсов для охоты на диких существ

Чекбоксы ресурсов:
- Яблоки (вкл по умолчанию)
- Листья (вкл по умолчанию)
- Грунт (вкл по умолчанию)
- Песок (вкл по умолчанию)
- Мёд (вкл по умолчанию)

Если ресурс выключен — бот не будет охотиться за этим ресурсом.

Сохраняется в gui_config.yaml:
  emulator_settings:
    '{emu_id}':
      wilds:
        resources:
          apples: true
          leaves: true
          soil: true
          sand: true
          honey: true

Версия: 1.0
Дата создания: 2025-03-11
"""

import customtkinter as ctk
from utils.config_manager import load_config, save_config


# Конфигурация ресурсов по умолчанию
# Порядок = порядок в панели автоохоты игры
DEFAULT_RESOURCES = {
    "apples": {"label": "🍎 Яблоки", "enabled": True},
    "leaves": {"label": "🌿 Листья", "enabled": True},
    "soil":   {"label": "🟤 Грунт", "enabled": True},
    "sand":   {"label": "🟡 Песок", "enabled": True},
    "honey":  {"label": "🍯 Мёд", "enabled": True},
}


class WildsSettingsWindow(ctk.CTkToplevel):
    """Окно настройки ресурсов для охоты на диких"""

    def __init__(self, parent, emulator_id, emulator_name):
        super().__init__(parent)

        self.emulator_id = emulator_id
        self.emulator_name = emulator_name

        # Настройки окна
        self.title(f"Дикие — {emulator_name}")
        self.resizable(False, False)
        self.grab_set()

        # Переменные чекбоксов
        self.resource_vars = {}  # {resource_key: BooleanVar}

        # Размер и позиция
        w, h = 320, 380
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
            text=f"🐻 Ресурсы для охоты — {self.emulator_name}",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        header.pack(pady=(15, 5))

        hint = ctk.CTkLabel(
            self,
            text="Бот будет охотиться только за\nвключёнными ресурсами",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E",
            justify="center"
        )
        hint.pack(pady=(0, 15))

        # Чекбоксы ресурсов
        cb_frame = ctk.CTkFrame(self, fg_color="transparent")
        cb_frame.pack(fill="x", padx=40, pady=5)

        for res_key, defaults in DEFAULT_RESOURCES.items():
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

        # Подсказка про мёд
        note = ctk.CTkLabel(
            self,
            text="ℹ️ Мёд фармится только если все\n"
                 "остальные ресурсы заполнены на 85%+",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E",
            justify="center"
        )
        note.pack(pady=(15, 5))

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

    def _load_settings(self):
        """Загружает настройки ресурсов из конфига"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(self.emulator_id)
        settings = emu_settings.get(emu_key, {})
        wilds = settings.get("wilds", {})
        resources = wilds.get("resources", {})

        for res_key, defaults in DEFAULT_RESOURCES.items():
            saved_value = resources.get(res_key, defaults["enabled"])
            self.resource_vars[res_key].set(saved_value)

    def _auto_save(self):
        """Сохраняет настройки ресурсов в gui_config.yaml"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}

        if "emulator_settings" not in gui_config:
            gui_config["emulator_settings"] = {}

        emu_key = str(self.emulator_id)
        if emu_key not in gui_config["emulator_settings"]:
            gui_config["emulator_settings"][emu_key] = {}

        if "wilds" not in gui_config["emulator_settings"][emu_key]:
            gui_config["emulator_settings"][emu_key]["wilds"] = {}

        resources_data = {}
        for res_key in DEFAULT_RESOURCES:
            resources_data[res_key] = self.resource_vars[res_key].get()

        gui_config["emulator_settings"][emu_key]["wilds"]["resources"] = \
            resources_data

        save_config("configs/gui_config.yaml", gui_config, silent=True)

    def _save_and_close(self):
        """Сохраняет и закрывает окно"""
        self._auto_save()
        self.destroy()