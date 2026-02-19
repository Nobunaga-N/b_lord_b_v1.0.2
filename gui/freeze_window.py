"""
Окно управления заморозками функций

Показывает все замороженные функции по эмуляторам.
Позволяет разморозить отдельные функции или все сразу.

Версия: 1.0
Дата создания: 2025-02-19
"""

import customtkinter as ctk
from datetime import datetime
from utils.function_freeze_manager import function_freeze_manager
from utils.logger import logger


# Человекочитаемые имена функций
FUNCTION_LABELS = {
    "building": "🏗 Строительство",
    "research": "🧬 Исследования",
    "evolution": "🧬 Эволюция",
    "feeding_zone": "🍖 Зона кормления",
    "ponds": "🌊 Пруды",
    "wilds": "🐻 Дикие",
    "coop": "🤝 Кооперации",
    "tiles": "🗺 Плитки",
    "prime_times": "⏰ Прайм таймы",
    "shield": "🛡 Щит",
    "mail_rewards": "📬 Почта",
}


class FreezeWindow(ctk.CTkToplevel):
    """Окно управления заморозками функций"""

    def __init__(self, parent, emulators: list = None):
        """
        Args:
            parent: родительское окно
            emulators: список эмуляторов [{id, name}, ...]
                       если None — берёт из parent.emulator_panel
        """
        super().__init__(parent)

        self.parent = parent
        self.emulators = emulators or self._get_emulators_from_parent()

        # Настройка окна
        self.title("🧊 Управление заморозками")
        self.geometry("700x500")
        self.resizable(True, True)

        # Модальное окно
        self.transient(parent)
        self.grab_set()

        self._center_window(parent)

        # Хранилище виджетов строк (для обновления)
        self._row_widgets = []

        # Создать UI
        self._create_ui()

        # Загрузить данные
        self._refresh_data()

        # Автообновление каждые 5 сек
        self._auto_refresh_id = None
        self._start_auto_refresh()

    # ===== ПОЛУЧЕНИЕ ЭМУЛЯТОРОВ =====

    def _get_emulators_from_parent(self) -> list:
        """Получить список эмуляторов из EmulatorPanel"""
        try:
            panel = self.parent.emulator_panel
            result = []
            for emu in panel.emulators:
                emu_id = emu.get("id", emu.get("index", 0))
                emu_name = emu.get("name", f"Emulator-{emu_id}")
                result.append({"id": emu_id, "name": emu_name})
            return result
        except Exception:
            return []

    # ===== ПОЗИЦИОНИРОВАНИЕ =====

    def _center_window(self, parent):
        """Центрирует окно относительно родительского"""
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = 700, 500
        self.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    # ===== UI =====

    def _create_ui(self):
        """Создаёт интерфейс"""

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Заголовок и кнопки ---
        header_frame = ctk.CTkFrame(main, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        self.header_label = ctk.CTkLabel(
            header_frame,
            text="🧊 Замороженные функции (0)",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.header_label.pack(side="left")

        btn_unfreeze_all = ctk.CTkButton(
            header_frame,
            text="🔓 Разморозить всё",
            command=self._unfreeze_all,
            width=160,
            height=32,
            fg_color="#28A745",
            hover_color="#218838"
        )
        btn_unfreeze_all.pack(side="right", padx=(10, 0))

        btn_refresh = ctk.CTkButton(
            header_frame,
            text="🔄 Обновить",
            command=self._refresh_data,
            width=110,
            height=32,
            fg_color="#6C757D",
            hover_color="#5A6268"
        )
        btn_refresh.pack(side="right")

        # --- Таблица (заголовки) ---
        columns_frame = ctk.CTkFrame(main, fg_color="#2B2B2B", corner_radius=8)
        columns_frame.pack(fill="x", pady=(0, 5))

        cols = [
            ("Эмулятор", 140),
            ("Функция", 140),
            ("Причина", 140),
            ("Разморозка", 100),
            ("Осталось", 80),
            ("", 60),
        ]

        for text, width in cols:
            ctk.CTkLabel(
                columns_frame,
                text=text,
                font=ctk.CTkFont(size=13, weight="bold"),
                width=width,
                anchor="w"
            ).pack(side="left", padx=8, pady=6)

        # --- Скроллируемая область с данными ---
        self.scroll_frame = ctk.CTkScrollableFrame(
            main,
            fg_color="transparent"
        )
        self.scroll_frame.pack(fill="both", expand=True)

        # --- Плейсхолдер "нет заморозок" ---
        self.empty_label = ctk.CTkLabel(
            self.scroll_frame,
            text="✅ Нет замороженных функций",
            font=ctk.CTkFont(size=15),
            text_color="#6C757D"
        )

    # ===== ЗАГРУЗКА ДАННЫХ =====

    def _refresh_data(self):
        """Перечитать заморозки и обновить таблицу"""

        # Очистить старые строки
        for widgets in self._row_widgets:
            for w in widgets:
                w.destroy()
        self._row_widgets.clear()

        # Собрать данные
        freezes = self._collect_freezes()

        # Обновить заголовок
        self.header_label.configure(
            text=f"🧊 Замороженные функции ({len(freezes)})"
        )

        if not freezes:
            self.empty_label.pack(pady=40)
            return

        self.empty_label.pack_forget()

        # Отрисовать строки
        now = datetime.now()
        for item in freezes:
            self._add_row(item, now)

    def _collect_freezes(self) -> list:
        """
        Собрать все заморозки из менеджера

        Returns:
            list[dict]: [{emulator_id, emulator_name, function,
                          unfreeze_at, reason}]
        """
        all_freezes = function_freeze_manager.get_all_freezes()
        now = datetime.now()

        # Маппинг id → name
        emu_names = {e["id"]: e["name"] for e in self.emulators}

        result = []
        for (emu_id, func_name), (unfreeze_at, reason) in all_freezes.items():
            if unfreeze_at <= now:
                continue  # Уже истекла

            result.append({
                "emulator_id": emu_id,
                "emulator_name": emu_names.get(emu_id, f"Emulator-{emu_id}"),
                "function": func_name,
                "unfreeze_at": unfreeze_at,
                "reason": reason or "—",
            })

        # Сортировка: сначала по эмулятору, потом по времени
        result.sort(key=lambda x: (x["emulator_id"], x["unfreeze_at"]))
        return result

    def _add_row(self, item: dict, now: datetime):
        """Добавить строку в таблицу"""

        row = ctk.CTkFrame(self.scroll_frame, fg_color="#1E1E1E",
                           corner_radius=6, height=36)
        row.pack(fill="x", pady=2, padx=2)
        row.pack_propagate(False)

        # Эмулятор
        lbl_emu = ctk.CTkLabel(
            row, text=item["emulator_name"],
            width=140, anchor="w",
            font=ctk.CTkFont(size=12)
        )
        lbl_emu.pack(side="left", padx=6)

        # Функция
        func_label = FUNCTION_LABELS.get(
            item["function"], f"❓ {item['function']}"
        )
        lbl_func = ctk.CTkLabel(
            row, text=func_label,
            width=140, anchor="w",
            font=ctk.CTkFont(size=12)
        )
        lbl_func.pack(side="left", padx=6)

        # Причина (обрезаем если длинная)
        reason_text = item.get("reason", "—")
        if len(reason_text) > 25:
            reason_text = reason_text[:22] + "..."
        lbl_reason = ctk.CTkLabel(
            row, text=reason_text,
            width=140, anchor="w",
            font=ctk.CTkFont(size=11),
            text_color="#AAAAAA"
        )
        lbl_reason.pack(side="left", padx=6)

        # Время разморозки
        lbl_time = ctk.CTkLabel(
            row, text=item["unfreeze_at"].strftime("%H:%M:%S"),
            width=100, anchor="w",
            font=ctk.CTkFont(size=12)
        )
        lbl_time.pack(side="left", padx=6)

        # Осталось
        remaining = item["unfreeze_at"] - now
        total_sec = max(0, int(remaining.total_seconds()))
        hours, rem = divmod(total_sec, 3600)
        minutes, secs = divmod(rem, 60)
        remaining_str = f"{hours}ч {minutes:02d}м"

        color = "#DC3545" if hours >= 2 else "#FFC107" if hours >= 1 else "#28A745"

        lbl_remain = ctk.CTkLabel(
            row, text=remaining_str,
            width=80, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=color
        )
        lbl_remain.pack(side="left", padx=6)

        # Кнопка разморозки
        emu_id = item["emulator_id"]
        func_name = item["function"]

        btn = ctk.CTkButton(
            row, text="🔓",
            width=45, height=26,
            fg_color="#17A2B8", hover_color="#138496",
            command=lambda e=emu_id, f=func_name: self._unfreeze_one(e, f)
        )
        btn.pack(side="left", padx=6)

        self._row_widgets.append([row, lbl_emu, lbl_func, lbl_reason,
                                  lbl_time, lbl_remain, btn])

    # ===== ДЕЙСТВИЯ =====

    def _unfreeze_one(self, emulator_id: int, function_name: str):
        """Разморозить одну функцию"""
        function_freeze_manager.unfreeze(emulator_id, function_name)
        logger.info(
            f"🔓 [GUI] Принудительная разморозка: "
            f"эмулятор={emulator_id}, функция={function_name}"
        )
        self._refresh_data()

    def _unfreeze_all(self):
        """Разморозить все функции на всех эмуляторах"""
        all_freezes = function_freeze_manager.get_all_freezes()
        if not all_freezes:
            return

        for (emu_id, func_name) in list(all_freezes.keys()):
            function_freeze_manager.unfreeze(emu_id, func_name)

        logger.info(
            f"🔓 [GUI] Принудительная разморозка ВСЕХ "
            f"({len(all_freezes)} шт.)"
        )
        self._refresh_data()

    # ===== АВТООБНОВЛЕНИЕ =====

    def _start_auto_refresh(self):
        """Автообновление каждые 5 секунд"""
        if not self.winfo_exists():
            return
        self._refresh_data()
        self._auto_refresh_id = self.after(5000, self._start_auto_refresh)

    def destroy(self):
        """Отмена автообновления при закрытии"""
        if self._auto_refresh_id:
            self.after_cancel(self._auto_refresh_id)
        super().destroy()