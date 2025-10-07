"""
Панель статуса
"""

import customtkinter as ctk


class StatusPanel(ctk.CTkFrame):
    """Панель статуса в реальном времени"""

    def __init__(self, parent):
        super().__init__(parent, corner_radius=10)

        # Данные статуса (заглушка)
        self.bot_state = {
            "is_running": False,
            "active_count": 0,
            "max_concurrent": 0,
            "active_emulators": []  # [{"id": 0, "name": "LDPlayer"}, ...]
        }

        # Создать UI
        self._create_ui()

        # Запустить механизм обновления
        self.start_updates()

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        # Заголовок
        header = ctk.CTkLabel(
            self,
            text="Статус",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(anchor="w", padx=15, pady=(10, 10))

        # Контейнер для основного контента
        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # === Строка 1: Состояние ===
        self.state_label = ctk.CTkLabel(
            content_frame,
            text="Состояние: 🔴 Остановлен",
            font=ctk.CTkFont(size=14),
            anchor="w"
        )
        self.state_label.pack(fill="x", pady=3)

        # === Строка 2: Активных эмуляторов ===
        self.active_label = ctk.CTkLabel(
            content_frame,
            text="Активных эмуляторов: 0 / 0",
            font=ctk.CTkFont(size=14),
            anchor="w"
        )
        self.active_label.pack(fill="x", pady=3)

        # === Заголовок списка ===
        list_header = ctk.CTkLabel(
            content_frame,
            text="Обрабатываются:",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w"
        )
        list_header.pack(fill="x", pady=(10, 5))

        # === Прокручиваемый список активных эмуляторов ===
        self.scroll_frame = ctk.CTkScrollableFrame(
            content_frame,
            height=120,
            fg_color="transparent"
        )
        self.scroll_frame.pack(fill="both", expand=True)

        # Заглушка для пустого списка
        self.empty_label = ctk.CTkLabel(
            self.scroll_frame,
            text="-",
            font=ctk.CTkFont(size=13),
            text_color="#9e9e9e"
        )
        self.empty_label.pack(pady=5)

    def start_updates(self):
        """Запускает периодическое обновление (каждые 2 секунды)"""
        self._update_status()

    def _update_status(self):
        """Обновляет отображение на основе состояния бота"""

        # TODO: В будущем здесь будет получение данных от BotController
        # Пока используем заглушку self.bot_state

        # Обновить состояние
        if self.bot_state["is_running"]:
            state_text = "Состояние: 🟢 Работает"
        else:
            state_text = "Состояние: 🔴 Остановлен"

        self.state_label.configure(text=state_text)

        # Обновить счётчик активных
        active_text = f"Активных эмуляторов: {self.bot_state['active_count']} / {self.bot_state['max_concurrent']}"
        self.active_label.configure(text=active_text)

        # Обновить список активных эмуляторов
        self._update_active_list()

        # Повторить через 2 секунды
        self.after(2000, self._update_status)

    def _update_active_list(self):
        """Обновляет список активных эмуляторов"""

        # Очистить старый список
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        active_emulators = self.bot_state.get("active_emulators", [])

        if not active_emulators:
            # Показать заглушку
            self.empty_label = ctk.CTkLabel(
                self.scroll_frame,
                text="-",
                font=ctk.CTkFont(size=13),
                text_color="#9e9e9e"
            )
            self.empty_label.pack(pady=5)
        else:
            # Показать список
            for emu in active_emulators:
                emu_text = f"• {emu['name']} (id:{emu['id']})"

                emu_label = ctk.CTkLabel(
                    self.scroll_frame,
                    text=emu_text,
                    font=ctk.CTkFont(size=13),
                    anchor="w"
                )
                emu_label.pack(anchor="w", pady=3, padx=5)

    def update_bot_state(self, bot_state):
        """
        Обновляет состояние бота (вызывается извне)

        Args:
            bot_state: dict с ключами:
                - is_running: bool
                - active_count: int
                - max_concurrent: int
                - active_emulators: list of {"id": int, "name": str}
        """
        self.bot_state = bot_state