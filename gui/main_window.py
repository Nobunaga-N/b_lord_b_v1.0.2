"""
Главное окно GUI

ОБНОВЛЕНО:
- Окно расширено до 900x700
- Трёхколоночный layout: StatusPanel (лево) | EmulatorPanel (центр) | Кнопки (право)
- StatusPanel — вертикальная панель с индикатором и списком активных эмуляторов
- Индикатор ● меняет цвет программно (зелёный/красный)
"""

import customtkinter as ctk
from gui.emulator_panel import EmulatorPanel
from gui.status_panel import StatusPanel
from gui.settings_window import SettingsWindow
from gui.functions_window import FunctionsWindow
from gui.error_log_window import ErrorLogWindow
from gui.bot_controller import BotController
from utils.error_log_manager import error_log_manager
from gui.schedule_window import ScheduleWindow
from gui.freeze_window import FreezeWindow


class MainWindow(ctk.CTk):
    """Главное окно приложения Beast Lord Bot v3.0"""

    def __init__(self):
        super().__init__()

        # Настройка окна (расширено для 3 колонок)
        self.title("Beast Lord Bot v1.0")
        self.geometry("970x700")
        self.resizable(False, False)

        # Установка темы
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Контроллер бота
        self.bot_controller = None

        # Кнопки
        self.btn_start = None
        self.btn_stop = None
        self.btn_error_log = None

        # Дочерние окна
        self.error_log_window = None
        self.schedule_window = None
        self.freeze_window = None

        # Создание структуры окна
        self._create_layout()

        # Инициализация контроллера бота (после создания панелей)
        self.bot_controller = BotController(gui_callback=self._on_bot_state_update)

        # Установить начальное состояние кнопок
        self._update_button_states()

        # Запустить периодическое обновление
        self._start_periodic_update()

    def _create_layout(self):
        """Создаёт трёхколоночную структуру окна"""

        padding = {"padx": 10, "pady": 10}

        # ============ Основной контейнер (3 колонки) ============
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, **padding)

        # === ЛЕВАЯ колонка: StatusPanel (фиксированная ширина) ===
        self.status_panel = StatusPanel(main_frame)
        self.status_panel.pack(side="left", fill="y", padx=(0, 5))

        # === ПРАВАЯ колонка: Кнопки (фиксированная ширина) ===
        buttons_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        buttons_frame.pack(side="right", fill="y", padx=(5, 0))

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

        # Кнопка "Журнал ошибок" с badge
        error_btn_container = ctk.CTkFrame(buttons_frame, fg_color="transparent")
        error_btn_container.pack(pady=5)

        self.btn_error_log = ctk.CTkButton(
            error_btn_container,
            text="📝 Журнал ошибок",
            command=self._open_error_log,
            width=150,
            height=35,
            fg_color="#6C757D",
            hover_color="#5A6268"
        )
        self.btn_error_log.pack()

        # Badge для ошибок
        self.error_badge = ctk.CTkLabel(
            error_btn_container,
            text="0",
            width=22, height=22,
            corner_radius=11,
            fg_color="#DC3545",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold")
        )

        # Кнопка "Уведомления" с badge
        notif_btn_container = ctk.CTkFrame(buttons_frame, fg_color="transparent")
        notif_btn_container.pack(pady=5)

        self.btn_notifications = ctk.CTkButton(
            notif_btn_container,
            text="🔔 Уведомления",
            command=self._open_notifications,
            width=150,
            height=35,
            fg_color="#6C757D",
            hover_color="#5A6268"
        )
        self.btn_notifications.pack()

        self.notif_badge = ctk.CTkLabel(
            notif_btn_container,
            text="0",
            width=22, height=22,
            corner_radius=11,
            fg_color="#DC3545",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold")
        )

        self._notif_blink_state = False
        self._notif_blink_job = None

        # Кнопка "Расписание"
        self.btn_schedule = ctk.CTkButton(
            buttons_frame,
            text="📅 Расписание",
            command=self._open_schedule,
            width=150,
            height=35,
            fg_color="#17A2B8",
            hover_color="#138496"
        )
        self.btn_schedule.pack(pady=5)

        # Кнопка "Заморозки"
        self.btn_freeze = ctk.CTkButton(
            buttons_frame,
            text="🧊 Заморозки",
            command=self._open_freeze_window,
            width=150,
            height=35,
            fg_color="#17A2B8",
            hover_color="#138496"
        )
        self.btn_freeze.pack(pady=5)

        # === ЦЕНТРАЛЬНАЯ колонка: EmulatorPanel (растягивается) ===
        self.emulator_panel = EmulatorPanel(main_frame)
        self.emulator_panel.pack(side="left", fill="both", expand=True, padx=5)

    # ===== УПРАВЛЕНИЕ БОТОМ =====

    def _on_start(self):
        """Обработка нажатия 'Запустить'"""
        self.bot_controller.start()

    def _on_stop(self):
        """Обработка нажатия 'Остановить'"""
        self.bot_controller.stop()

    def _open_settings(self):
        """Открыть окно настроек"""
        SettingsWindow(self)

    def _open_functions(self):
        """Открыть окно функций"""
        FunctionsWindow(self)

    def _open_error_log(self):
        """Открыть окно журнала ошибок"""
        if self.error_log_window and self.error_log_window.winfo_exists():
            self.error_log_window.lift()
            self.error_log_window.focus()
        else:
            self.error_log_window = ErrorLogWindow(self)

    def _open_schedule(self):
        """Открыть окно расписания планировщика"""
        if self.schedule_window and self.schedule_window.winfo_exists():
            self.schedule_window.lift()
            self.schedule_window.focus()
        else:
            self.schedule_window = ScheduleWindow(self, self.bot_controller)

    def _open_freeze_window(self):
        """Открыть окно управления заморозками"""
        if self.freeze_window and self.freeze_window.winfo_exists():
            self.freeze_window.lift()
            self.freeze_window.focus()
        else:
            self.freeze_window = FreezeWindow(self)

    # ===== ОБНОВЛЕНИЕ UI =====

    def _update_error_badge(self):
        """Обновить badge с количеством ошибок"""
        try:
            count = error_log_manager.get_error_count()

            if count > 0:
                self.error_badge.configure(text=str(count))
                self.error_badge.place(x=125, y=5)
                self.btn_error_log.configure(fg_color="#DC3545", hover_color="#C82333")
            else:
                self.error_badge.place_forget()
                self.btn_error_log.configure(fg_color="#6C757D", hover_color="#5A6268")
        except Exception:
            pass

    def _update_button_states(self):
        """Обновляет состояние кнопок в зависимости от состояния бота"""
        if self.bot_controller and self.bot_controller.orchestrator:
            is_running = self.bot_controller.orchestrator.is_running

            if is_running:
                self.btn_start.configure(state="disabled")
                self.btn_stop.configure(state="normal")
            else:
                self.btn_start.configure(state="normal")
                self.btn_stop.configure(state="disabled")

    def _on_bot_state_update(self, bot_state):
        """
        Единый callback от BotOrchestrator
        Распределяет данные по всем панелям GUI
        """
        # 1. Обновить StatusPanel
        self.status_panel.update_bot_state(bot_state)

        # 2. Обновить индикаторы в EmulatorPanel
        active_ids = {emu["id"] for emu in bot_state.get("active_emulators", [])}
        running_ids = bot_state.get("running_ids", set())
        self.emulator_panel.update_indicators(
            active_ids=active_ids,
            running_ids=running_ids
        )

    def _start_periodic_update(self):
        """Запускает периодическое обновление UI"""
        self._update_button_states()

        # Проверяем флаг новых ошибок (thread-safe)
        if error_log_manager.check_new_errors():
            self._update_error_badge()

        self.after(500, self._start_periodic_update)

    # ===== УВЕДОМЛЕНИЯ =====

    def _open_notifications(self):
        """Открывает окно уведомлений"""
        from gui.notifications_window import NotificationsWindow
        NotificationsWindow(self)

    def _check_notifications(self):
        """Периодическая проверка новых уведомлений (каждые 3 сек)"""
        from gui.notifications_window import get_new_notification_count
        count = get_new_notification_count()
        self._update_notif_badge(count)
        self.after(3000, self._check_notifications)

    def _update_notif_badge(self, count):
        """Обновляет badge и мигание"""
        if count > 0:
            self.notif_badge.configure(text=str(count))
            self.notif_badge.place(relx=1.0, rely=0.0, anchor="ne", x=-5, y=-3)
            if self._notif_blink_job is None:
                self._blink_notification_button()
        else:
            self.notif_badge.place_forget()
            self.btn_notifications.configure(fg_color="#6C757D")
            if self._notif_blink_job is not None:
                self.after_cancel(self._notif_blink_job)
                self._notif_blink_job = None

    def _blink_notification_button(self):
        """Мигание кнопки уведомлений"""
        from gui.notifications_window import get_new_notification_count
        if get_new_notification_count() == 0:
            self.btn_notifications.configure(fg_color="#6C757D")
            self._notif_blink_job = None
            return

        self._notif_blink_state = not self._notif_blink_state
        color = "#DC3545" if self._notif_blink_state else "#6C757D"
        self.btn_notifications.configure(fg_color=color)
        self._notif_blink_job = self.after(800, self._blink_notification_button)

    def update_notification_badge(self):
        """Вызывается извне для обновления badge"""
        from gui.notifications_window import get_new_notification_count
        count = get_new_notification_count()
        self._update_notif_badge(count)