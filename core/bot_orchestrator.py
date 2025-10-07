"""
Главный оркестратор бота
"""

import time
import threading
from utils.logger import logger
from utils.config_manager import load_config
from utils.adb_controller import wait_for_adb
from core.emulator_manager import EmulatorManager
from core.game_launcher import GameLauncher
from core.function_executor import execute_functions


class BotOrchestrator:
    """Управление главным циклом бота"""

    def __init__(self, gui_callback=None):
        """
        Инициализация оркестратора

        Args:
            gui_callback: функция для обновления GUI (опционально)
                         Формат: callback(bot_state)
        """
        # Состояние
        self.is_running = False
        self.thread = None
        self.gui_callback = gui_callback

        # Данные
        self.queue = []
        self.active_slots = []  # [(emulator, thread), ...]
        self.max_concurrent = 3

        # Компоненты
        self.emulator_manager = EmulatorManager()

        logger.debug("BotOrchestrator инициализирован")

    def start(self):
        """Запускает бота в отдельном потоке"""

        if self.is_running:
            logger.warning("Бот уже запущен")
            return False

        logger.info("Запуск бота...")

        # Установить флаг
        self.is_running = True

        # Создать поток
        self.thread = threading.Thread(target=self._main_loop, daemon=False)
        self.thread.start()

        logger.success("Бот запущен в отдельном потоке")
        return True

    def stop(self):
        """Останавливает бот gracefully"""

        if not self.is_running:
            logger.warning("Бот уже остановлен")
            return

        logger.info("Остановка бота...")

        # 1. Установить флаг (главный цикл перестанет запускать новые)
        self.is_running = False

        # 2. Дождаться завершения главного потока
        if self.thread and self.thread.is_alive():
            logger.info("Ожидание завершения главного потока...")
            self.thread.join()  # Без таймаута!

        # 3. Дождаться завершения всех активных потоков
        for emulator, thread in self.active_slots[:]:
            if thread.is_alive():
                logger.info(f"Ожидание завершения: {emulator['name']}...")
                thread.join()  # Без таймаута!

        # 4. Принудительно закрыть все эмуляторы (на всякий случай)
        for emulator, _ in self.active_slots:
            logger.info(f"Закрытие эмулятора: {emulator['name']}")
            self.emulator_manager.stop_emulator(emulator['id'])

        # 5. Очистить данные
        self.active_slots = []
        self.queue = []

        logger.success("Бот остановлен")
        self._update_gui()

    def _main_loop(self):
        """Главный цикл (выполняется в отдельном потоке)"""

        logger.info("Запуск главного цикла бота...")

        try:
            # 1. Загрузить конфиг
            enabled_emulators, self.max_concurrent, active_functions = self._load_config()

            if not enabled_emulators:
                logger.warning("Нет выбранных эмуляторов, завершение")
                self.is_running = False
                self._update_gui()
                return

            # 2. Создать очередь
            self.queue = enabled_emulators.copy()
            self.active_slots = []

            logger.info(f"Всего эмуляторов: {len(self.queue)}, макс одновременно: {self.max_concurrent}")
            logger.info(f"Активные функции: {active_functions if active_functions else 'НЕТ'}")

            # 3. Главный цикл
            while self.is_running and (self.queue or self.active_slots):

                # 3a. Запустить новые потоки до max_concurrent
                while len(self.active_slots) < self.max_concurrent and self.queue and self.is_running:
                    emulator = self.queue.pop(0)

                    logger.info(f"Запуск обработки: {emulator['name']} (слот {len(self.active_slots)+1}/{self.max_concurrent})")

                    # Запустить в отдельном потоке
                    thread = threading.Thread(
                        target=self._process_emulator,
                        args=(emulator, active_functions),
                        daemon=False
                    )
                    thread.start()

                    self.active_slots.append((emulator, thread))
                    self._update_gui()

                # 3b. Проверить завершенные потоки
                for emulator, thread in self.active_slots[:]:
                    if not thread.is_alive():
                        logger.success(f"Слот освобожден: {emulator['name']}")
                        self.active_slots.remove((emulator, thread))
                        self._update_gui()

                # 3c. Пауза
                time.sleep(1)

            # 4. Завершение
            logger.info("Все эмуляторы обработаны, главный цикл завершен")

        except Exception as e:
            logger.error(f"Ошибка в главном цикле: {e}")
            logger.exception(e)

        finally:
            self.is_running = False
            self._update_gui()

    def _process_emulator(self, emulator, active_functions):
        """
        Обработка одного эмулятора (выполняется в отдельном потоке)

        Args:
            emulator: словарь с данными эмулятора
            active_functions: список активных функций
        """

        emulator_name = emulator['name']

        try:
            # 1. Запустить эмулятор
            logger.info(f"[{emulator_name}] Запуск эмулятора...")
            if not self.emulator_manager.start_emulator(emulator['id']):
                logger.error(f"[{emulator_name}] Не удалось запустить эмулятор")
                return

            # 2. Ждать ADB
            logger.info(f"[{emulator_name}] Ожидание ADB...")
            if not wait_for_adb(emulator['port'], timeout=90):
                logger.error(f"[{emulator_name}] ADB не готов, пропускаю")
                return

            logger.success(f"[{emulator_name}] ADB готов")

            # 3. Запустить игру и дождаться загрузки
            game_launcher = GameLauncher(emulator)
            if not game_launcher.launch_and_wait():
                logger.error(f"[{emulator_name}] Игра не загрузилась, пропускаю")
                return

            # 4. Проверить активные функции
            if not active_functions:
                logger.info(f"[{emulator_name}] Нет активных функций, задания выполнены")
                return

            # 5. Выполнить функции по порядку
            logger.info(f"[{emulator_name}] Выполнение функций: {active_functions}")
            execute_functions(emulator, active_functions)

            logger.success(f"[{emulator_name}] Обработка завершена")

        except Exception as e:
            logger.error(f"[{emulator_name}] Ошибка: {e}")
            logger.exception(e)

        finally:
            # Всегда закрыть эмулятор
            logger.info(f"[{emulator_name}] Закрытие эмулятора...")
            self.emulator_manager.stop_emulator(emulator['id'])

    def _load_config(self):
        """
        Загружает конфигурацию бота

        Returns:
            tuple: (enabled_emulators, max_concurrent, active_functions)
                - enabled_emulators: список словарей с эмуляторами
                - max_concurrent: int, макс одновременных эмуляторов
                - active_functions: список названий активных функций
        """

        # Загрузить gui_config.yaml
        gui_config = load_config("configs/gui_config.yaml")

        if not gui_config:
            logger.error("Не удалось загрузить gui_config.yaml")
            return [], 3, []

        # Получить ID включенных эмуляторов
        enabled_ids = gui_config.get('emulators', {}).get('enabled', [])

        # Получить max_concurrent
        max_concurrent = gui_config.get('settings', {}).get('max_concurrent', 3)

        # Получить активные функции
        functions_config = gui_config.get('functions', {})
        active_functions = [name for name, enabled in functions_config.items() if enabled]

        # Загрузить emulators.yaml
        emulators_config = load_config("configs/emulators.yaml")

        if not emulators_config or 'emulators' not in emulators_config:
            logger.error("Не удалось загрузить emulators.yaml")
            return [], max_concurrent, active_functions

        all_emulators = emulators_config['emulators']

        # Фильтровать только включенные
        enabled_emulators = [emu for emu in all_emulators if emu['id'] in enabled_ids]

        logger.debug(f"Загружено эмуляторов: {len(enabled_emulators)}, макс одновременно: {max_concurrent}")
        logger.debug(f"Активные функции: {active_functions}")

        return enabled_emulators, max_concurrent, active_functions

    def _update_gui(self):
        """Обновляет GUI через callback"""

        if not self.gui_callback:
            return

        # Формируем состояние
        bot_state = {
            "is_running": self.is_running,
            "active_count": len(self.active_slots),
            "max_concurrent": self.max_concurrent,
            "active_emulators": [
                {"id": emu['id'], "name": emu['name']}
                for emu, _ in self.active_slots
            ]
        }

        # Вызываем callback
        try:
            self.gui_callback(bot_state)
        except Exception as e:
            logger.error(f"Ошибка при обновлении GUI: {e}")