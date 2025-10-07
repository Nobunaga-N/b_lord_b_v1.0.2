"""
Главное окно GUI
"""

import customtkinter as ctk
from gui.emulator_panel import EmulatorPanel
from gui.functions_panel import FunctionsPanel
from gui.settings_panel import SettingsPanel


class MainWindow(ctk.CTk):
    """Главное окно приложения Beast Lord Bot v3.0"""

    def __init__(self):
        super().__init__()

        # Настройка окна
        self.title("Beast Lord Bot v3.0")
        self.geometry("700x950")  # ← БЫЛО 900, СТАЛО 950
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
        self.emulator_panel.pack(fill="both", **padding)  # ← УБРАЛИ expand=True

        # ============ Панель 2: Функции ============
        self.functions_panel = FunctionsPanel(self)
        self.functions_panel.pack(fill="x", **padding)

        # ============ Панель 3: Настройки ============
        self.settings_panel = SettingsPanel(self)
        self.settings_panel.pack(fill="x", **padding)

        # ============ Панель 4: Статус ============
        self.status_frame = ctk.CTkFrame(self, corner_radius=10)
        self.status_frame.pack(fill="x", **padding)

        status_label = ctk.CTkLabel(
            self.status_frame,
            text="Статус",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        status_label.pack(anchor="w", padx=15, pady=(10, 5))

        # Временная заглушка для статуса
        status_content = ctk.CTkLabel(
            self.status_frame,
            text="Состояние: 🔴 Остановлен\nАктивных эмуляторов: 0 / 0\nОчередь: 0",
            font=ctk.CTkFont(size=13),
            justify="left"
        )
        status_content.pack(anchor="w", padx=15, pady=(5, 15))

        # ============ Панель 5: Кнопки управления ============
        self.control_frame = ctk.CTkFrame(self, corner_radius=10)
        self.control_frame.pack(fill="x", **padding)

        # Кнопки управления (только Запустить и Остановить)
        btn_start = ctk.CTkButton(
            self.control_frame,
            text="▶ Запустить",
            width=180,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._on_start
        )
        btn_start.pack(side="left", padx=15, pady=15)

        btn_stop = ctk.CTkButton(
            self.control_frame,
            text="⏹ Остановить",
            width=180,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#d32f2f",
            hover_color="#b71c1c",
            command=self._on_stop
        )
        btn_stop.pack(side="left", padx=5, pady=15)

    def _on_start(self):
        """Обработчик кнопки 'Запустить' (пока заглушка)"""
        print("\n[INFO] Кнопка 'Запустить' нажата")
        print(f"  - Выбрано эмуляторов: {len(self.emulator_panel.get_selected_emulator_ids())}")
        print(f"  - ID эмуляторов: {self.emulator_panel.get_selected_emulator_ids()}")
        print(f"  - Активных функций: {self.functions_panel.get_active_functions()}")
        print(f"  - Max concurrent: {self.settings_panel.get_max_concurrent()}")
        print("[INFO] TODO: Реализовать запуск бота на следующих этапах\n")

    def _on_stop(self):
        """Обработчик кнопки 'Остановить' (пока заглушка)"""
        print("\n[INFO] Кнопка 'Остановить' нажата")
        print("[INFO] TODO: Реализовать остановку бота на следующих этапах\n")