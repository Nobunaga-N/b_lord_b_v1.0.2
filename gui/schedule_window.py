"""
Окно расписания планировщика
Отображает очередь эмуляторов, активные слоты и статистику

Версия: 1.0
Дата создания: 2025-02-11
"""

import customtkinter as ctk
from datetime import datetime


class ScheduleWindow(ctk.CTkToplevel):
    """Окно отображения расписания планировщика"""

    # Цвета статусов
    STATUS_COLORS = {
        "processing": "#28A745",  # Зелёный — в работе
        "new": "#FF6B00",         # Оранжевый — новый эмулятор
        "ready": "#FFC107",       # Жёлтый — готов к запуску
        "waiting": "#6C757D",     # Серый — ожидание
    }

    STATUS_LABELS = {
        "processing": "⚙️ в работе",
        "new": "🆕 новый",
        "ready": "✅ готов",
        "waiting": "⏳ ожидание",
    }

    def __init__(self, parent, bot_controller):
        """
        Инициализация окна расписания

        Args:
            parent: родительское окно (MainWindow)
            bot_controller: контроллер бота (для доступа к оркестратору)
        """
        super().__init__(parent)

        self.bot_controller = bot_controller

        # Настройка окна
        self.title("📅 Расписание планировщика")
        self.geometry("750x600")
        self.resizable(True, True)

        # Сделать окно модальным
        self.transient(parent)
        self.grab_set()

        # Центрировать
        self._center_window(parent)

        # Создать UI
        self._create_ui()

        # Загрузить данные
        self._refresh_data()

        # Запустить автообновление
        self._auto_refresh()

    def _center_window(self, parent):
        """Центрирует окно относительно родительского"""
        self.update_idletasks()

        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        window_width = 750
        window_height = 600

        x = parent_x + (parent_width - window_width) // 2
        y = parent_y + (parent_height - window_height) // 2

        self.geometry(f"{window_width}x{window_height}+{x}+{y}")

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # === ВЕРХНЯЯ ПАНЕЛЬ: Заголовок + Статистика + Обновить ===
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        self.header_label = ctk.CTkLabel(
            header_frame,
            text="📅 Расписание планировщика",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.header_label.pack(side="left")

        # Кнопка обновить
        btn_refresh = ctk.CTkButton(
            header_frame,
            text="🔄 Обновить",
            command=self._refresh_data,
            width=100
        )
        btn_refresh.pack(side="right", padx=5)

        # Время обновления
        self.updated_label = ctk.CTkLabel(
            header_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E"
        )
        self.updated_label.pack(side="right", padx=10)

        # === СТАТИСТИКА ===
        stats_frame = ctk.CTkFrame(main_frame, fg_color="#2B2B2B", corner_radius=8)
        stats_frame.pack(fill="x", pady=(0, 10))

        stats_inner = ctk.CTkFrame(stats_frame, fg_color="transparent")
        stats_inner.pack(padx=15, pady=10)

        # Статистика в одну строку
        self.stats_label = ctk.CTkLabel(
            stats_inner,
            text="Загрузка...",
            font=ctk.CTkFont(size=13),
            anchor="w"
        )
        self.stats_label.pack(anchor="w")

        # === ОСНОВНАЯ ОБЛАСТЬ: Прокручиваемый список ===
        self.scrollable_frame = ctk.CTkScrollableFrame(
            main_frame,
            fg_color="#1E1E1E"
        )
        self.scrollable_frame.pack(fill="both", expand=True)

    def _refresh_data(self):
        """Обновить данные расписания"""

        # Получить данные от оркестратора
        snapshot = self._get_snapshot()

        if not snapshot or not snapshot.get('updated_at'):
            self._show_no_data()
            return

        # Обновить время
        self.updated_label.configure(text=f"Обновлено: {snapshot['updated_at']}")

        # Обновить статистику
        active_count = len(snapshot.get('active', []))
        queue_count = len(snapshot.get('queue', []))
        idle_count = snapshot.get('idle_count', 0)
        total = snapshot.get('total_enabled', 0)
        max_c = snapshot.get('max_concurrent', 0)

        stats_text = (
            f"🟢 Активные слоты: {active_count}/{max_c}   │   "
            f"📋 В очереди: {queue_count}   │   "
            f"💤 Без задач: {idle_count}   │   "
            f"📊 Всего включено: {total}"
        )
        self.stats_label.configure(text=stats_text)

        # Очистить список
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        # === СЕКЦИЯ: Активные слоты ===
        active = snapshot.get('active', [])
        if active:
            self._create_section_header("⚙️ В работе", len(active))
            for item in active:
                self._create_item_row(
                    name=item['emulator_name'],
                    status="processing",
                    detail="обработка функций"
                )

        # === СЕКЦИЯ: Очередь ===
        queue = snapshot.get('queue', [])

        # Разделяем на подкатегории
        new_items = [q for q in queue if q['status'] == 'new']
        ready_items = [q for q in queue if q['status'] == 'ready']
        waiting_items = [q for q in queue if q['status'] == 'waiting']

        if new_items:
            self._create_section_header("🆕 Новые (первичное сканирование)", len(new_items))
            for item in new_items:
                reasons_str = ", ".join(item.get('reasons', []))
                self._create_item_row(
                    name=item['emulator_name'],
                    status="new",
                    detail=f"инициализация ({reasons_str})"
                )

        if ready_items:
            self._create_section_header("✅ Готовы к запуску", len(ready_items))
            for item in ready_items:
                reasons_str = ", ".join(item.get('reasons', []))
                self._create_item_row(
                    name=item['emulator_name'],
                    status="ready",
                    detail=reasons_str
                )

        if waiting_items:
            self._create_section_header("⏳ Запланированы", len(waiting_items))
            for item in waiting_items:
                reasons_str = ", ".join(item.get('reasons', []))
                wait_str = f"через {item['wait_minutes']}м" if item['wait_minutes'] > 0 else ""
                time_str = item.get('launch_time', '')
                self._create_item_row(
                    name=item['emulator_name'],
                    status="waiting",
                    detail=f"{time_str} {wait_str} — {reasons_str}"
                )

        # === СЕКЦИЯ: Без задач ===
        if idle_count > 0:
            self._create_section_header(f"💤 Без задач (всё готово)", idle_count)
            idle_label = ctk.CTkLabel(
                self.scrollable_frame,
                text=f"   {idle_count} эмуляторов — все здания на максимуме или функции отключены",
                font=ctk.CTkFont(size=12),
                text_color="#6C757D",
                anchor="w"
            )
            idle_label.pack(fill="x", padx=10, pady=5)

        # Если вообще ничего нет
        if not active and not queue and idle_count == 0:
            self._show_no_data()

    def _create_section_header(self, title, count):
        """Создать заголовок секции"""
        header = ctk.CTkLabel(
            self.scrollable_frame,
            text=f"{title} ({count})",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w"
        )
        header.pack(fill="x", padx=10, pady=(15, 5))

        # Разделитель
        separator = ctk.CTkFrame(self.scrollable_frame, height=1, fg_color="#3B3B3B")
        separator.pack(fill="x", padx=10, pady=(0, 5))

    def _create_item_row(self, name, status, detail):
        """
        Создать строку элемента расписания

        Args:
            name: имя эмулятора
            status: статус (processing/new/ready/waiting)
            detail: дополнительная информация
        """
        row_frame = ctk.CTkFrame(
            self.scrollable_frame,
            fg_color="#2B2B2B",
            corner_radius=6,
            height=40
        )
        row_frame.pack(fill="x", padx=10, pady=2)
        row_frame.pack_propagate(False)

        # Цветной индикатор
        color = self.STATUS_COLORS.get(status, "#6C757D")
        indicator = ctk.CTkFrame(row_frame, width=4, fg_color=color, corner_radius=2)
        indicator.pack(side="left", fill="y", padx=(5, 10), pady=5)

        # Имя эмулятора
        name_label = ctk.CTkLabel(
            row_frame,
            text=name,
            font=ctk.CTkFont(size=12, weight="bold"),
            width=150,
            anchor="w"
        )
        name_label.pack(side="left", padx=(0, 10), pady=5)

        # Статус
        status_text = self.STATUS_LABELS.get(status, status)
        status_label = ctk.CTkLabel(
            row_frame,
            text=status_text,
            font=ctk.CTkFont(size=11),
            text_color=color,
            width=100,
            anchor="w"
        )
        status_label.pack(side="left", padx=(0, 10), pady=5)

        # Детали
        detail_label = ctk.CTkLabel(
            row_frame,
            text=detail,
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E",
            anchor="w"
        )
        detail_label.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=5)

    def _show_no_data(self):
        """Показать заглушку когда нет данных"""
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        placeholder = ctk.CTkLabel(
            self.scrollable_frame,
            text="Бот не запущен или нет данных расписания\n\n"
                 "Нажмите ▶ Запустить чтобы начать работу.\n"
                 "Планировщик автоматически рассчитает расписание\n"
                 "на основе таймеров строительства в БД.",
            font=ctk.CTkFont(size=13),
            text_color="#6C757D",
            justify="center"
        )
        placeholder.pack(expand=True, pady=50)

    def _get_snapshot(self):
        """Получить данные от оркестратора"""
        try:
            if (self.bot_controller and
                    self.bot_controller.orchestrator and
                    self.bot_controller.orchestrator.is_running):
                return self.bot_controller.orchestrator.get_schedule_snapshot()
        except Exception:
            pass
        return None

    def _auto_refresh(self):
        """Автоматическое обновление каждые 5 секунд"""
        if self.winfo_exists():
            self._refresh_data()
            self.after(5000, self._auto_refresh)