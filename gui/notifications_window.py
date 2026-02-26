"""
Система уведомлений о готовности отрядов

Хранит уведомления в gui_config.yaml в разделе "notifications".
Каждое уведомление:
  - emulator_id, emulator_name
  - squad (название отряда)
  - timestamp
  - status: "new" / "read" / "done"

Версия: 1.0
"""

import customtkinter as ctk
from datetime import datetime
from utils.config_manager import load_config, save_config


class NotificationsWindow(ctk.CTkToplevel):
    """Окно уведомлений о готовности отрядов"""

    def __init__(self, parent):
        super().__init__(parent)

        self.parent_ref = parent  # для обновления badge

        self.title("Уведомления — Готовность отрядов")
        self.resizable(True, True)
        self.grab_set()

        w, h = 600, 450
        self._center_window(parent, w, h)

        self._create_ui()
        self._refresh_list()

    def _center_window(self, parent, w, h):
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
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(10, 5))

        self.header_label = ctk.CTkLabel(
            header_frame,
            text="🔔 Уведомления (0)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.header_label.pack(side="left")

        btn_clear_done = ctk.CTkButton(
            header_frame,
            text="🗑️ Удалить выполненные",
            width=180,
            height=30,
            fg_color="#DC3545",
            hover_color="#C82333",
            command=self._clear_done
        )
        btn_clear_done.pack(side="right")

        # Прокручиваемый список
        self.scroll_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent"
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=15, pady=10)

    def _refresh_list(self):
        """Обновляет список уведомлений"""
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        notifications = self._load_notifications()

        self.header_label.configure(
            text=f"🔔 Уведомления ({len(notifications)})"
        )

        if not notifications:
            ctk.CTkLabel(
                self.scroll_frame,
                text="Нет уведомлений",
                font=ctk.CTkFont(size=13),
                text_color="#9E9E9E"
            ).pack(pady=20)
            return

        for i, notif in enumerate(notifications):
            self._create_notification_row(i, notif)

    def _create_notification_row(self, index, notif):
        """Создаёт строку уведомления"""

        status = notif.get("status", "new")
        if status == "done":
            bg_color = "#1B3D1B"  # тёмно-зелёный
        elif status == "read":
            bg_color = "#3D3B1B"  # тёмно-жёлтый
        else:
            bg_color = "#3D1B1B"  # тёмно-красный (новое)

        row = ctk.CTkFrame(self.scroll_frame, fg_color=bg_color, corner_radius=8)
        row.pack(fill="x", pady=3)

        # Текст
        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True, padx=10, pady=8)

        status_emoji = {"new": "🔴", "read": "🟡", "done": "✅"}.get(status, "❓")

        ctk.CTkLabel(
            info_frame,
            text=f"{status_emoji} {notif.get('emulator_name', '?')} — {notif.get('squad', '?')}",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(anchor="w")

        ctk.CTkLabel(
            info_frame,
            text=f"Время: {notif.get('timestamp', '?')}",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E",
            anchor="w"
        ).pack(anchor="w")

        # Кнопки
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=10, pady=5)

        if status == "new":
            ctk.CTkButton(
                btn_frame,
                text="👁 Прочитано",
                width=100, height=28,
                fg_color="#FFC107",
                hover_color="#E0A800",
                text_color="#000000",
                command=lambda idx=index: self._mark_read(idx)
            ).pack(pady=2)

        if status in ("new", "read"):
            ctk.CTkButton(
                btn_frame,
                text="✅ Сделано",
                width=100, height=28,
                fg_color="#28A745",
                hover_color="#218838",
                command=lambda idx=index: self._mark_done(idx)
            ).pack(pady=2)

    # ===== ДЕЙСТВИЯ =====

    def _mark_read(self, index):
        """Помечает уведомление как прочитанное"""
        self._update_notification_status(index, "read")

    def _mark_done(self, index):
        """Помечает уведомление как выполненное"""
        self._update_notification_status(index, "done")

    def _update_notification_status(self, index, new_status):
        """Обновляет статус уведомления"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        notifications = gui_config.get("notifications", [])

        if 0 <= index < len(notifications):
            notifications[index]["status"] = new_status
            gui_config["notifications"] = notifications
            save_config("configs/gui_config.yaml", gui_config, silent=True)

        self._refresh_list()
        self._update_parent_badge()

    def _clear_done(self):
        """Удаляет все выполненные уведомления"""
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        notifications = gui_config.get("notifications", [])
        notifications = [n for n in notifications if n.get("status") != "done"]
        gui_config["notifications"] = notifications
        save_config("configs/gui_config.yaml", gui_config, silent=True)
        self._refresh_list()
        self._update_parent_badge()

    def _update_parent_badge(self):
        """Обновляет badge на кнопке в главном окне"""
        try:
            main_window = self.parent_ref.winfo_toplevel()
            if hasattr(main_window, 'update_notification_badge'):
                main_window.update_notification_badge()
        except Exception:
            pass

    # ===== ЗАГРУЗКА/СОХРАНЕНИЕ =====

    def _load_notifications(self):
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        return gui_config.get("notifications", [])


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (вызываются из кода бота) =====

def add_notification(emulator_id, emulator_name, squad_name):
    """
    Добавляет уведомление о готовности отряда

    Вызывается из кода бота (функции эволюции и т.д.)

    Args:
        emulator_id: ID эмулятора
        emulator_name: имя эмулятора
        squad_name: название отряда ("Отряд II", "Отряд III")
    """
    gui_config = load_config("configs/gui_config.yaml", silent=True) or {}

    if "notifications" not in gui_config:
        gui_config["notifications"] = []

    notification = {
        "emulator_id": emulator_id,
        "emulator_name": emulator_name,
        "squad": squad_name,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "new"
    }

    gui_config["notifications"].append(notification)
    save_config("configs/gui_config.yaml", gui_config, silent=True)


def get_new_notification_count():
    """Возвращает количество непрочитанных уведомлений"""
    gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
    notifications = gui_config.get("notifications", [])
    return sum(1 for n in notifications if n.get("status") == "new")