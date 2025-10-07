"""
Главное окно GUI
"""

import customtkinter as ctk
from gui.emulator_panel import EmulatorPanel
from gui.status_panel import StatusPanel
from gui.settings_window import SettingsWindow
from gui.functions_window import FunctionsWindow


class MainWindow(ctk.CTk):
    """Главное окно приложения Beast Lord Bot v3.0"""

    def __init__(self):
        super().__init__()

        # Настройка окна
        self.title("Beast Lord Bot v3.0")
        self.geometry("700x700")
        self.resizable(False, False)

        # Установка темы
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Создание структуры окна
        self._create_layout()

    def _create_layout(self):
        """Создаёт базовую структуру окна"""

        # Отступы
        padding = {"padx": 10, "pady": 10}

        # ============ Верхняя часть: Эмуляторы + Кнопки ============
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="both", expand=True, **padding)

        # === Левая часть: Эмуляторы ===
        self.emulator_panel = EmulatorPanel(top_frame)
        self.emulator_panel.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # === Правая часть: Кнопки ===
        buttons_frame = ctk.CTkFrame(top_frame, corner_radius=10)
        buttons_frame.pack(side="left", fill="y", padx=(5, 0))

        # Заголовок кнопок
        btn_header = ctk.CTkLabel(
            buttons_frame,
            text="Управление",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        btn_header.pack(pady=(15, 10))

        # Кнопка "Запустить"
        btn_start = ctk.CTkButton(
            buttons_frame,
            text="▶ Запустить",
            width=150,
            height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_start
        )
        btn_start.pack(pady=5, padx=15)

        # Кнопка "Остановить"
        btn_stop = ctk.CTkButton(
            buttons_frame,
            text="⏹ Остановить",
            width=150,
            height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#d32f2f",
            hover_color="#b71c1c",
            command=self._on_stop
        )
        btn_stop.pack(pady=5, padx=15)

        # Кнопка "Настройки"
        btn_settings = ctk.CTkButton(
            buttons_frame,
            text="⚙️ Настройки",
            width=150,
            height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_settings
        )
        btn_settings.pack(pady=5, padx=15)

        # Кнопка "Функции"
        btn_functions = ctk.CTkButton(
            buttons_frame,
            text="📋 Функции",
            width=150,
            height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_functions
        )
        btn_functions.pack(pady=(5, 15), padx=15)

        # ============ Панель 2: Статус ============
        self.status_panel = StatusPanel(self)
        self.status_panel.pack(fill="both", expand=True, **padding)

    def _on_start(self):
        """Обработчик кнопки 'Запустить' (пока заглушка)"""
        print("\n[INFO] Кнопка 'Запустить' нажата")
        print("[INFO] TODO: Реализовать запуск бота на следующих этапах\n")

    def _on_stop(self):
        """Обработчик кнопки 'Остановить' (пока заглушка)"""
        print("\n[INFO] Кнопка 'Остановить' нажата")
        print("[INFO] TODO: Реализовать остановку бота на следующих этапах\n")

    def _on_settings(self):
        """Открывает окно настроек"""
        SettingsWindow(self)

    def _on_functions(self):
        """Открывает окно функций"""
        FunctionsWindow(self)