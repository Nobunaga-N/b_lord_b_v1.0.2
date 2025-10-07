"""
Всплывающее окно настроек
"""

import customtkinter as ctk
from utils.config_manager import load_config, save_config


class SettingsWindow(ctk.CTkToplevel):
    """Модальное окно настроек (max_concurrent)"""

    def __init__(self, parent):
        super().__init__(parent)

        # Настройка окна
        self.title("Настройки")
        self.geometry("500x200")
        self.resizable(False, False)

        # Сделать окно модальным
        self.transient(parent)
        self.grab_set()

        # Центрировать относительно родителя
        self._center_window(parent)

        # Данные
        self.max_concurrent_var = ctk.IntVar(value=3)
        self.save_timer = None

        # Создать UI
        self._create_ui()

        # Загрузить настройки
        self._load_settings()

    def _center_window(self, parent):
        """Центрирует окно относительно родительского"""
        self.update_idletasks()

        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        window_width = 500
        window_height = 200

        x = parent_x + (parent_width - window_width) // 2
        y = parent_y + (parent_height - window_height) // 2

        self.geometry(f"{window_width}x{window_height}+{x}+{y}")

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        # Основной фрейм
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Заголовок
        header = ctk.CTkLabel(
            main_frame,
            text="⚙️ Настройки бота",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        header.pack(pady=(0, 20))

        # Фрейм для слайдера
        slider_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        slider_frame.pack(fill="x", pady=10)

        # Метка
        label = ctk.CTkLabel(
            slider_frame,
            text="Максимум одновременных эмуляторов:",
            font=ctk.CTkFont(size=14)
        )
        label.pack(pady=(0, 10))

        # Контейнер для слайдера и значения
        slider_container = ctk.CTkFrame(slider_frame, fg_color="transparent")
        slider_container.pack()

        # Слайдер
        self.slider = ctk.CTkSlider(
            slider_container,
            from_=1,
            to=20,
            number_of_steps=19,
            variable=self.max_concurrent_var,
            command=self._on_slider_change,
            width=350
        )
        self.slider.pack(side="left", padx=(0, 15))

        # Значение
        self.value_label = ctk.CTkLabel(
            slider_container,
            text="3",
            font=ctk.CTkFont(size=16, weight="bold"),
            width=40
        )
        self.value_label.pack(side="left")

        # Диапазон
        range_label = ctk.CTkLabel(
            slider_frame,
            text="(1-20)",
            font=ctk.CTkFont(size=12),
            text_color="#9e9e9e"
        )
        range_label.pack(pady=(5, 0))

    def _load_settings(self):
        """Загружает настройки из конфига"""
        gui_config = load_config("configs/gui_config.yaml", silent=True)

        if gui_config and "settings" in gui_config:
            max_concurrent = gui_config["settings"].get("max_concurrent", 3)
            self.max_concurrent_var.set(max_concurrent)
            self.value_label.configure(text=str(max_concurrent))

    def _on_slider_change(self, value):
        """Обработчик изменения слайдера"""
        int_value = int(round(value))
        self.value_label.configure(text=str(int_value))

        # Debounce сохранения
        if self.save_timer is not None:
            self.after_cancel(self.save_timer)

        self.save_timer = self.after(500, self._auto_save_settings)

    def _auto_save_settings(self):
        """Автосохранение настроек"""
        max_concurrent = int(round(self.max_concurrent_var.get()))

        gui_config = load_config("configs/gui_config.yaml", silent=True)

        if not gui_config:
            gui_config = {
                "emulators": {"enabled": []},
                "functions": {},
                "settings": {}
            }

        if "settings" not in gui_config:
            gui_config["settings"] = {}

        gui_config["settings"]["max_concurrent"] = max_concurrent
        save_config("configs/gui_config.yaml", gui_config, silent=True)

        self.save_timer = None