"""
Окно настройки прайм-таймов для конкретного эмулятора

Настройки:
- Чекбоксы типов drain: Строительство, Тренировка, Эволюция
  (все включены по умолчанию)

Если тип отключён — choose_drain_type() не рассматривает его
как кандидата, даже если ускорений хватает.

Сохраняется в gui_config.yaml:
  emulator_settings:
    '{emu_id}':
      prime_times:
        drain_types:
          building: true
          training: true
          evolution: true

Версия: 1.0
Дата создания: 2025-04-03
"""

import customtkinter as ctk
from typing import Dict, List, Optional

from utils.config_manager import load_config, save_config


# ═══════════════════════════════════════════════════
# DEFAULTS
# ═══════════════════════════════════════════════════

DEFAULT_DRAIN_TYPES = {
    "building":  {"label": "🏗️ Строительство", "enabled": True},
    "training":  {"label": "⚔️ Тренировка",    "enabled": True},
    "evolution": {"label": "🧬 Эволюция",      "enabled": True},
}


# ═══════════════════════════════════════════════════
# ПУБЛИЧНАЯ ФУНКЦИЯ (используется из speedup_calculator)
# ═══════════════════════════════════════════════════

def load_allowed_drain_types(emulator_id: int) -> List[str]:
    """
    Загрузить список разрешённых drain-типов для эмулятора.

    Читает gui_config.yaml → emulator_settings → {emu_id} →
    prime_times → drain_types.

    Returns:
        ['building', 'training', 'evolution'] — только включённые.
        Если конфига нет или секция отсутствует — все три типа
        (по умолчанию всё включено).
    """
    gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
    emu_settings = gui_config.get("emulator_settings", {})
    settings = emu_settings.get(str(emulator_id), {})
    prime = settings.get("prime_times", {})
    drain_types = prime.get("drain_types", {})

    if not drain_types:
        # Конфиг ещё не создан — все типы разрешены
        return list(DEFAULT_DRAIN_TYPES.keys())

    allowed = []
    for dtype, defaults in DEFAULT_DRAIN_TYPES.items():
        if drain_types.get(dtype, defaults["enabled"]):
            allowed.append(dtype)

    return allowed


# ═══════════════════════════════════════════════════
# GUI ОКНО
# ═══════════════════════════════════════════════════

class PrimeTimesSettingsWindow(ctk.CTkToplevel):
    """Окно настройки прайм-таймов для конкретного эмулятора"""

    def __init__(self, parent, emulator_id, emulator_name):
        super().__init__(parent)

        self.emulator_id = emulator_id
        self.emulator_name = emulator_name

        # Настройки окна
        self.title(f"Прайм-таймы — {emulator_name}")
        self.resizable(False, False)
        self.grab_set()

        # Переменные чекбоксов
        self.drain_vars: Dict[str, ctk.BooleanVar] = {}

        # Размер и позиция
        w, h = 320, 300
        self._center_window(parent, w, h)

        # UI
        self._create_ui()

        # Загрузить сохранённые данные
        self._load_settings()

    def _center_window(self, parent, w, h):
        """Центрирует окно относительно родителя"""
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
            text=f"⏱ Прайм-таймы — {self.emulator_name}",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        header.pack(pady=(15, 5))

        hint = ctk.CTkLabel(
            self,
            text="Выберите типы ДС, в которых\n"
                 "бот будет тратить ускорения:",
            font=ctk.CTkFont(size=12),
            text_color="#9E9E9E",
            justify="center"
        )
        hint.pack(pady=(0, 10))

        # Фрейм для чекбоксов
        cb_frame = ctk.CTkFrame(self, fg_color="transparent")
        cb_frame.pack(fill="x", padx=30, pady=5)

        for dtype, info in DEFAULT_DRAIN_TYPES.items():
            var = ctk.BooleanVar(value=info["enabled"])
            self.drain_vars[dtype] = var

            cb = ctk.CTkCheckBox(
                cb_frame,
                text=info["label"],
                variable=var,
                font=ctk.CTkFont(size=13),
                command=self._on_change
            )
            cb.pack(anchor="w", pady=5)

        # Подсказка
        note = ctk.CTkLabel(
            self,
            text="ℹ️ Если тип отключён — бот не будет\n"
                 "выбирать его даже при наличии ускорений.\n"
                 "Удобно для тестирования конкретного типа.",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E",
            justify="left"
        )
        note.pack(padx=20, pady=(10, 5))

        # Кнопка закрыть
        btn_close = ctk.CTkButton(
            self,
            text="💾 Сохранить и закрыть",
            width=180,
            height=35,
            fg_color="#28A745",
            hover_color="#218838",
            command=self._save_and_close
        )
        btn_close.pack(pady=(10, 15))

    # ===== ЛОГИКА =====

    def _on_change(self):
        """Автосохранение при переключении чекбокса"""
        self._auto_save()

    def _load_settings(self):
        """Загружает настройки из конфига"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(self.emulator_id)
        settings = emu_settings.get(emu_key, {})
        prime = settings.get("prime_times", {})
        drain_types = prime.get("drain_types", {})

        for dtype, defaults in DEFAULT_DRAIN_TYPES.items():
            saved = drain_types.get(dtype, defaults["enabled"])
            self.drain_vars[dtype].set(saved)

    def _auto_save(self):
        """Сохраняет настройки в gui_config.yaml"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}

        if "emulator_settings" not in gui_config:
            gui_config["emulator_settings"] = {}

        emu_key = str(self.emulator_id)
        if emu_key not in gui_config["emulator_settings"]:
            gui_config["emulator_settings"][emu_key] = {}

        drain_data = {}
        for dtype in DEFAULT_DRAIN_TYPES:
            drain_data[dtype] = self.drain_vars[dtype].get()

        gui_config["emulator_settings"][emu_key]["prime_times"] = {
            "drain_types": drain_data,
        }

        save_config("configs/gui_config.yaml", gui_config, silent=True)

    def _save_and_close(self):
        """Сохраняет и закрывает окно"""
        self._auto_save()
        self.destroy()