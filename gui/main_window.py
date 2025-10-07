"""
Главное окно GUI
"""

import customtkinter as ctk
from gui.emulator_panel import EmulatorPanel


class MainWindow(ctk.CTk):
    """Главное окно приложения Beast Lord Bot v3.0"""

    def __init__(self):
        super().__init__()

        # Настройка окна
        self.title("Beast Lord Bot v3.0")
        self.geometry("700x900")
        self.resizable(False, False)  # Фиксированный размер

        # Установка темы
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Создание структуры окна
        self._create_layout()

    def _create_layout(self):
        """Создаёт базовую структуру с 5 панелями"""

        # Отступы для всех панелей
        padding = {"padx": 10, "pady": 10}

        # ============ Панель 1: Эмуляторы ============
        self.emulator_panel = EmulatorPanel(self)
        self.emulator_panel.pack(fill="both", expand=True, **padding)

        # ============ Панель 2: Функции ============
        self.functions_frame = ctk.CTkFrame(self, corner_radius=10)
        self.functions_frame.pack(fill="x", **padding)

        functions_label = ctk.CTkLabel(
            self.functions_frame,
            text="Функции (изолированное тестирование)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        functions_label.pack(anchor="w", padx=15, pady=(10, 5))

        # ============ Панель 3: Настройки ============
        self.settings_frame = ctk.CTkFrame(self, corner_radius=10)
        self.settings_frame.pack(fill="x", **padding)

        settings_label = ctk.CTkLabel(
            self.settings_frame,
            text="Настройки",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        settings_label.pack(anchor="w", padx=15, pady=(10, 5))

        # ============ Панель 4: Статус ============
        self.status_frame = ctk.CTkFrame(self, corner_radius=10)
        self.status_frame.pack(fill="x", **padding)

        status_label = ctk.CTkLabel(
            self.status_frame,
            text="Статус",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        status_label.pack(anchor="w", padx=15, pady=(10, 5))

        # ============ Панель 5: Кнопки управления ============
        self.control_frame = ctk.CTkFrame(self, corner_radius=10)
        self.control_frame.pack(fill="x", **padding)

        # Временные кнопки (пока без функционала)
        btn_start = ctk.CTkButton(
            self.control_frame,
            text="▶ Запустить",
            width=180,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        btn_start.pack(side="left", padx=15, pady=15)

        btn_stop = ctk.CTkButton(
            self.control_frame,
            text="⏹ Остановить",
            width=180,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#d32f2f",
            hover_color="#b71c1c"
        )
        btn_stop.pack(side="left", padx=5, pady=15)

        btn_save = ctk.CTkButton(
            self.control_frame,
            text="💾 Сохранить настройки",
            width=220,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#388e3c",
            hover_color="#2e7d32"
        )
        btn_save.pack(side="left", padx=5, pady=15)