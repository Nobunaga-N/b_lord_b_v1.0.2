"""
Панель настроек
"""

import customtkinter as ctk
from utils.config_manager import load_config, save_config


class SettingsPanel(ctk.CTkFrame):
    """Панель настроек (max_concurrent и др.)"""

    def __init__(self, parent):
        super().__init__(parent, corner_radius=10)

        # Данные
        self.max_concurrent_var = ctk.IntVar(value=3)
        self.save_timer = None  # Таймер для debounce сохранения

        # Создать UI
        self._create_ui()

        # Загрузить настройки
        self._load_settings()

    def _create_ui(self):
        """Создаёт элементы интерфейса"""

        # Заголовок
        header = ctk.CTkLabel(
            self,
            text="Настройки",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(anchor="w", padx=15, pady=(10, 5))

        # Контейнер для слайдера
        slider_frame = ctk.CTkFrame(self, fg_color="transparent")
        slider_frame.pack(fill="x", padx=15, pady=(5, 15))

        # Метка слайдера
        slider_label = ctk.CTkLabel(
            slider_frame,
            text="Макс одновременно:",
            font=ctk.CTkFont(size=13)
        )
        slider_label.pack(side="left", padx=(0, 10))

        # Слайдер (от 1 до 20)
        self.slider = ctk.CTkSlider(
            slider_frame,
            from_=1,
            to=20,
            number_of_steps=19,  # 1, 2, 3, ..., 20
            variable=self.max_concurrent_var,
            command=self._on_slider_change,
            width=250
        )
        self.slider.pack(side="left", padx=(0, 10))

        # Отображение текущего значения
        self.value_label = ctk.CTkLabel(
            slider_frame,
            text="3",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=30
        )
        self.value_label.pack(side="left")

        # Диапазон (справка)
        range_label = ctk.CTkLabel(
            slider_frame,
            text="(1-20)",
            font=ctk.CTkFont(size=12),
            text_color="#9e9e9e"
        )
        range_label.pack(side="left", padx=(5, 0))

    def _load_settings(self):
        """Загружает настройки из gui_config.yaml"""

        # Загрузить конфиг
        gui_config = load_config("configs/gui_config.yaml")

        if not gui_config or "settings" not in gui_config:
            return

        # Установить значение max_concurrent
        max_concurrent = gui_config["settings"].get("max_concurrent", 3)
        self.max_concurrent_var.set(max_concurrent)
        self.value_label.configure(text=str(max_concurrent))

    def _on_slider_change(self, value):
        """
        Обработчик изменения слайдера

        Args:
            value: Новое значение (float)
        """
        # Округлить до целого
        int_value = int(round(value))

        # Обновить отображение
        self.value_label.configure(text=str(int_value))

        # Отменить предыдущий таймер сохранения (если есть)
        if self.save_timer is not None:
            self.after_cancel(self.save_timer)

        # Запустить новый таймер (сохранение через 500мс после последнего изменения)
        self.save_timer = self.after(500, self._auto_save_settings)

    def _auto_save_settings(self):
        """Автоматически сохраняет настройки в gui_config.yaml (с debounce)"""

        # Получить текущее значение
        max_concurrent = int(round(self.max_concurrent_var.get()))

        # Загрузить существующий конфиг (БЕЗ вывода в консоль)
        gui_config = load_config("configs/gui_config.yaml", silent=True)

        # Если конфиг пустой - создать базовую структуру
        if not gui_config:
            gui_config = {
                "emulators": {"enabled": []},
                "functions": {
                    "building": False,
                    "research": False,
                    "wilds": False,
                    "coop": False,
                    "tiles": False,
                    "prime_times": False,
                    "shield": False,
                    "mail_rewards": False
                },
                "settings": {}
            }

        # Обновить настройки
        if "settings" not in gui_config:
            gui_config["settings"] = {}
        gui_config["settings"]["max_concurrent"] = max_concurrent

        # Сохранить (БЕЗ вывода в консоль)
        save_config("configs/gui_config.yaml", gui_config, silent=True)

        # Сбросить таймер
        self.save_timer = None

    def get_max_concurrent(self):
        """
        Возвращает текущее значение max_concurrent

        Returns:
            int: Максимальное количество одновременных эмуляторов (1-20)
        """
        return int(round(self.max_concurrent_var.get()))