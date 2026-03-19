"""
Панель статуса (вертикальная, слева от списка эмуляторов)

Показывает:
  - Индикатор состояния (● Работает / ● Остановлен) с динамическим цветом
  - Счётчик активных слотов
  - Скролл-список активных эмуляторов (имя + id)

Ширина фиксирована ~200px, высота растягивается.
"""

import customtkinter as ctk


class StatusPanel(ctk.CTkFrame):
    """Вертикальная панель статуса (левая колонка)"""

    COLOR_GREEN = "#28A745"
    COLOR_RED = "#DC3545"
    COLOR_GRAY = "#6C757D"

    def __init__(self, parent):
        super().__init__(parent, corner_radius=10, width=290)
        self.pack_propagate(False)  # Фиксированная ширина

        # Данные статуса
        self.bot_state = {
            "is_running": False,
            "active_count": 0,
            "max_concurrent": 0,
            "active_emulators": []
        }

        self._create_ui()
        self.start_updates()

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        # === Заголовок ===
        header = ctk.CTkLabel(
            self,
            text="Статус",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(anchor="w", padx=12, pady=(10, 5))

        # === Строка состояния: ● Работает / ● Остановлен ===
        state_row = ctk.CTkFrame(self, fg_color="transparent")
        state_row.pack(fill="x", padx=12, pady=(0, 3))

        self.indicator = ctk.CTkLabel(
            state_row,
            text="●",
            font=ctk.CTkFont(size=16),
            text_color=self.COLOR_RED,
            width=18
        )
        self.indicator.pack(side="left", padx=(0, 4))

        self.state_label = ctk.CTkLabel(
            state_row,
            text="Остановлен",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#9e9e9e"
        )
        self.state_label.pack(side="left")

        # === Счётчик активных ===
        self.active_label = ctk.CTkLabel(
            self,
            text="Активных: 0 / 0",
            font=ctk.CTkFont(size=12),
            text_color="#9e9e9e",
            anchor="w"
        )
        self.active_label.pack(fill="x", padx=12, pady=(0, 8))

        # === Разделитель ===
        sep = ctk.CTkFrame(self, height=1, fg_color="#3B3B3B")
        sep.pack(fill="x", padx=12, pady=(0, 5))

        # === Заголовок списка ===
        list_header = ctk.CTkLabel(
            self,
            text="В работе:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        )
        list_header.pack(fill="x", padx=12, pady=(0, 3))

        # === Скролл-список активных эмуляторов ===
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent"
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Заглушка
        self.empty_label = ctk.CTkLabel(
            self.scroll_frame,
            text="—",
            font=ctk.CTkFont(size=12),
            text_color="#6C757D"
        )
        self.empty_label.pack(pady=5)

    def start_updates(self):
        """Запускает периодическое обновление"""
        self._update_status()

    def _update_status(self):
        """Обновляет отображение на основе bot_state"""

        is_running = self.bot_state.get("is_running", False)

        # Индикатор + текст состояния
        if is_running:
            self.indicator.configure(text_color=self.COLOR_GREEN)
            self.state_label.configure(text="Работает", text_color=self.COLOR_GREEN)
        else:
            self.indicator.configure(text_color=self.COLOR_RED)
            self.state_label.configure(text="Остановлен", text_color="#9e9e9e")

        # Счётчик
        active = self.bot_state.get("active_count", 0)
        max_c = self.bot_state.get("max_concurrent", 0)
        self.active_label.configure(text=f"Активных: {active} / {max_c}")

        # Обновить список
        self._update_active_list()

        # Повторить через 2 секунды
        self.after(2000, self._update_status)

    def _update_active_list(self):
        """Обновляет скролл-список активных эмуляторов"""

        # Очистить
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        active_emulators = self.bot_state.get("active_emulators", [])

        if not active_emulators:
            self.empty_label = ctk.CTkLabel(
                self.scroll_frame,
                text="—",
                font=ctk.CTkFont(size=12),
                text_color="#6C757D"
            )
            self.empty_label.pack(pady=5)
        else:
            for emu in active_emulators:
                emu_name = emu.get("name", f"id:{emu.get('id', '?')}")
                emu_id = emu.get("id", "?")

                row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
                row.pack(fill="x", pady=1)

                # Зелёный кружок
                dot = ctk.CTkLabel(
                    row,
                    text="●",
                    font=ctk.CTkFont(size=10),
                    text_color=self.COLOR_GREEN,
                    width=14
                )
                dot.pack(side="left", padx=(0, 4))

                # Имя (обрезается если длинное)
                name_label = ctk.CTkLabel(
                    row,
                    text=f"{emu_name}",
                    font=ctk.CTkFont(size=12),
                    anchor="w"
                )
                name_label.pack(side="left", fill="x", expand=True)

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