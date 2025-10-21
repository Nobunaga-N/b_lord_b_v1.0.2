"""
Главное окно GUI
С поддержкой журнала критических ошибок
"""

import customtkinter as ctk
from gui.emulator_panel import EmulatorPanel
from gui.status_panel import StatusPanel
from gui.settings_window import SettingsWindow
from gui.functions_window import FunctionsWindow
from gui.error_log_window import ErrorLogWindow
from gui.bot_controller import BotController
from utils.error_log_manager import error_log_manager


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

        # Контроллер бота (будет инициализирован после создания панелей)
        self.bot_controller = None

        # Кнопки (для управления состоянием)
        self.btn_start = None
        self.btn_stop = None
        self.btn_error_log = None

        # Окно журнала ошибок
        self.error_log_window = None

        # Создание структуры окна
        self._create_layout()

        # Инициализация контроллера бота (после создания status_panel)
        self.bot_controller = BotController(gui_callback=self.status_panel.update_bot_state)

        # Установить начальное состояние кнопок
        self._update_button_states()

        # Настроить колбэк для обновления badge ошибок
        error_log_manager.set_gui_callback(self._update_error_badge)

        # Запустить периодическое обновление кнопок
        self._start_periodic_update()

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
        buttons_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        buttons_frame.pack(side="right", fill="y")

        # Кнопка "Запустить"
        self.btn_start = ctk.CTkButton(
            buttons_frame,
            text="▶ Запустить",
            command=self._on_start,
            width=150,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#28A745",
            hover_color="#218838"
        )
        self.btn_start.pack(pady=5)

        # Кнопка "Остановить"
        self.btn_stop = ctk.CTkButton(
            buttons_frame,
            text="⏹ Остановить",
            command=self._on_stop,
            width=150,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#DC3545",
            hover_color="#C82333"
        )
        self.btn_stop.pack(pady=5)

        # Разделитель
        separator = ctk.CTkFrame(buttons_frame, height=2, fg_color="#3B3B3B")
        separator.pack(fill="x", pady=10)

        # Кнопка "Настройки"
        btn_settings = ctk.CTkButton(
            buttons_frame,
            text="⚙️ Настройки",
            command=self._open_settings,
            width=150,
            height=35
        )
        btn_settings.pack(pady=5)

        # Кнопка "Функции"
        btn_functions = ctk.CTkButton(
            buttons_frame,
            text="📋 Функции",
            command=self._open_functions,
            width=150,
            height=35
        )
        btn_functions.pack(pady=5)

        # === НОВОЕ: Кнопка "Журнал ошибок" ===
        error_btn_frame = ctk.CTkFrame(buttons_frame, fg_color="transparent")
        error_btn_frame.pack(pady=5)

        self.btn_error_log = ctk.CTkButton(
            error_btn_frame,
            text="🔴 Журнал ошибок",
            command=self._open_error_log,
            width=150,
            height=35,
            fg_color="#6C757D",
            hover_color="#5A6268"
        )
        self.btn_error_log.pack()

        # Badge для количества ошибок
        self.error_badge = ctk.CTkLabel(
            error_btn_frame,
            text="0",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="white",
            fg_color="#DC3545",
            corner_radius=10,
            width=20,
            height=20
        )
        # Изначально скрыт

        # ============ Нижняя часть: Статус ============
        self.status_panel = StatusPanel(self)
        self.status_panel.pack(fill="both", expand=True, **padding)

    def _on_start(self):
        """Обработка нажатия "Запустить" """
        self.bot_controller.start()

    def _on_stop(self):
        """Обработка нажатия "Остановить" """
        self.bot_controller.stop()

    def _open_settings(self):
        """Открыть окно настроек"""
        SettingsWindow(self)

    def _open_functions(self):
        """Открыть окно функций"""
        FunctionsWindow(self)

    def _open_error_log(self):
        """Открыть окно журнала ошибок"""
        # Если окно уже открыто - поднять на передний план
        if self.error_log_window and self.error_log_window.winfo_exists():
            self.error_log_window.lift()
            self.error_log_window.focus()
        else:
            # Создать новое окно
            self.error_log_window = ErrorLogWindow(self)

    def _update_error_badge(self):
        """Обновить badge с количеством ошибок"""
        try:
            count = error_log_manager.get_error_count()

            if count > 0:
                # Показать badge
                self.error_badge.configure(text=str(count))
                self.error_badge.place(x=125, y=5)

                # Изменить цвет кнопки если есть ошибки
                self.btn_error_log.configure(fg_color="#DC3545", hover_color="#C82333")
            else:
                # Скрыть badge
                self.error_badge.place_forget()

                # Вернуть обычный цвет кнопки
                self.btn_error_log.configure(fg_color="#6C757D", hover_color="#5A6268")
        except Exception:
            pass  # Игнорируем ошибки в обновлении badge

    def _update_button_states(self):
        """Обновляет состояние кнопок в зависимости от состояния бота"""
        if self.bot_controller and self.bot_controller.orchestrator:
            is_running = self.bot_controller.orchestrator.is_running

            # Управление кнопками
            if is_running:
                self.btn_start.configure(state="disabled")
                self.btn_stop.configure(state="normal")
            else:
                self.btn_start.configure(state="normal")
                self.btn_stop.configure(state="disabled")

    def _start_periodic_update(self):
        """Запускает периодическое обновление UI"""
        self._update_button_states()
        self._update_error_badge()

        # Обновлять каждые 500 мс
        self.after(500, self._start_periodic_update)