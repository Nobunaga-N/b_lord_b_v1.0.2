"""
Окно настроек конкретного эмулятора

Открывается по клику на ⚙️ в панели эмуляторов.
Содержит кнопку "Вожаки" (и в будущем другие настройки).

Версия: 1.0
"""

import customtkinter as ctk


class EmulatorSettingsWindow(ctk.CTkToplevel):
    """Окно настроек эмулятора"""

    def __init__(self, parent, emulator_id, emulator_name):
        super().__init__(parent)

        self.emulator_id = emulator_id
        self.emulator_name = emulator_name

        # Настройки окна
        self.title(f"Настройки — {emulator_name} (id:{emulator_id})")
        self.resizable(False, False)
        self.grab_set()

        # Размер и позиция
        w, h = 300, 200
        self._center_window(parent, w, h)

        # UI
        self._create_ui()

    def _center_window(self, parent, w, h):
        """Центрирует окно"""
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
            text=f"⚙️ {self.emulator_name}",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(pady=(15, 20))

        # Кнопка "Вожаки"
        btn_leaders = ctk.CTkButton(
            self,
            text="🐾 Вожаки (Отряды)",
            width=200,
            height=40,
            font=ctk.CTkFont(size=14),
            fg_color="#7B2D8E",
            hover_color="#5E2170",
            command=self._open_leaders
        )
        btn_leaders.pack(pady=5)

        # Разделитель
        sep = ctk.CTkLabel(
            self,
            text="— Будущие настройки —",
            font=ctk.CTkFont(size=11),
            text_color="#6C757D"
        )
        sep.pack(pady=(20, 5))

        # Закрыть
        btn_close = ctk.CTkButton(
            self,
            text="Закрыть",
            width=100,
            height=30,
            fg_color="#6C757D",
            hover_color="#5A6268",
            command=self.destroy
        )
        btn_close.pack(pady=10)

    def _open_leaders(self):
        """Открывает окно настройки вожаков/отрядов"""
        from gui.leaders_window import LeadersWindow
        LeadersWindow(self, self.emulator_id, self.emulator_name)