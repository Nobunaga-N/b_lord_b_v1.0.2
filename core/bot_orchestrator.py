"""
Главный оркестратор бота Beast Lord Bot v3.0
С интегрированной системой восстановления (Recovery System)

Версия: 1.1
Дата создания: 2025-01-06
Последнее обновление: 2025-01-16 (добавлена Recovery System)
"""

import time
import threading
from utils.logger import logger
from utils.config_manager import load_config
from utils.adb_controller import wait_for_adb
from utils.recovery_manager import recovery_manager
from core.emulator_manager import EmulatorManager
from core.game_launcher import GameLauncher
from core.function_executor import execute_functions


class BotOrchestrator:
    """
    Управление главным циклом бота

    Основные возможности:
    - Динамическое управление слотами (max_concurrent)
    - Обработка эмуляторов в параллельных потоках
    - Graceful shutdown без зависаний
    - Интеграция с Recovery System для обработки ошибок
    - Автоматический перезапуск эмуляторов при критических ошибках
    """

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

                # 3a. Проверка запросов на перезапуск для активных эмуляторов
                self._check_restart_requests()

                # 3b. Запустить новые потоки до max_concurrent
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

                # 3c. Проверить завершенные потоки
                for emulator, thread in self.active_slots[:]:
                    if not thread.is_alive():
                        logger.success(f"Слот освобожден: {emulator['name']}")
                        self.active_slots.remove((emulator, thread))
                        self._update_gui()

                # 3d. Пауза
                time.sleep(1)

            # 4. Завершение
            logger.info("Главный цикл завершён")
            self.is_running = False
            self._update_gui()

        except Exception as e:
            logger.error(f"Критическая ошибка в главном цикле: {e}")
            logger.exception(e)
            self.is_running = False
            self._update_gui()

    def _check_restart_requests(self):
        """
        Проверка запросов на перезапуск эмуляторов

        Если есть запрос на перезапуск активного эмулятора,
        логирует предупреждение (перезапуск произойдет в _process_emulator)
        """
        for emulator, thread in self.active_slots[:]:
            emulator_id = emulator.get('id')

            if recovery_manager.has_restart_request(emulator_id) and thread.is_alive():
                reason = recovery_manager.get_restart_reason(emulator_id)
                logger.warning(f"🔄 Эмулятор {emulator['name']} имеет запрос на перезапуск: {reason}")
                logger.info(f"⏳ Ожидание завершения текущей обработки перед перезапуском...")

    def _process_emulator(self, emulator, active_functions):
        """
        Обрабатывает один эмулятор
        С поддержкой Recovery System

        Args:
            emulator: словарь с данными эмулятора
            active_functions: список активных функций
        """
        emulator_name = emulator.get('name', 'Unknown')
        emulator_id = emulator.get('id')

        try:
            logger.info(f"\n{'='*50}")
            logger.info(f"🎮 Обработка эмулятора: {emulator_name}")
            logger.info(f"{'='*50}")

            # НОВОЕ: Проверка запроса на перезапуск
            if recovery_manager.has_restart_request(emulator_id):
                reason = recovery_manager.get_restart_reason(emulator_id)
                logger.warning(f"[{emulator_name}] 🔄 Обнаружен запрос на перезапуск: {reason}")

                # Выполняем перезапуск
                success = self._restart_emulator(emulator)

                if success:
                    logger.success(f"[{emulator_name}] ✅ Эмулятор успешно перезапущен")
                    recovery_manager.clear_restart_request(emulator_id)
                else:
                    logger.error(f"[{emulator_name}] ❌ Не удалось перезапустить эмулятор")
                    # Пропускаем этот эмулятор в текущем цикле
                    return

            # 1. Запустить эмулятор
            logger.info(f"[{emulator_name}] Запуск эмулятора...")
            if not self.emulator_manager.start_emulator(emulator_id):
                logger.error(f"[{emulator_name}] ❌ Не удалось запустить эмулятор")
                return

            # 2. Дождаться ADB
            logger.info(f"[{emulator_name}] Ожидание ADB...")
            if not wait_for_adb(emulator['port']):
                logger.error(f"[{emulator_name}] ❌ ADB не готов")
                self.emulator_manager.stop_emulator(emulator)
                return

            # 3. Запустить игру и дождаться загрузки
            game_launcher = GameLauncher(emulator)
            if not game_launcher.launch_and_wait():
                logger.error(f"[{emulator_name}] ❌ Игра не загрузилась")

                # НОВОЕ: Обработка ошибки загрузки игры
                recovery_manager.handle_stuck_state(emulator, context="Игра не загрузилась")
                self.emulator_manager.stop_emulator(emulator)
                return

            # 4. Проверить активные функции
            if not active_functions:
                logger.info(f"[{emulator_name}] Нет активных функций, задания выполнены")
                return

            # 5. Выполнить функции по порядку
            logger.info(f"[{emulator_name}] Выполнение функций: {active_functions}")

            try:
                execute_functions(emulator, active_functions)
                logger.success(f"[{emulator_name}] ✅ Все функции выполнены")
            except Exception as func_error:
                logger.error(f"[{emulator_name}] ❌ Ошибка при выполнении функций: {func_error}")

                # НОВОЕ: Обработка ошибки выполнения функций
                recovery_manager.handle_stuck_state(emulator, context=f"Ошибка функций: {func_error}")

        except Exception as e:
            logger.error(f"[{emulator_name}] ❌ Критическая ошибка в обработке: {e}")
            logger.exception(e)

            # НОВОЕ: Обработка критической ошибки
            recovery_manager.handle_stuck_state(emulator, context=f"Критическая ошибка: {e}")

        finally:
            # Всегда закрыть эмулятор
            logger.info(f"[{emulator_name}] Закрытие эмулятора...")
            try:
                self.emulator_manager.stop_emulator(emulator['id'])
            except Exception as close_error:
                logger.error(f"[{emulator_name}] ⚠️ Ошибка при закрытии эмулятора: {close_error}")

            logger.info(f"[{emulator_name}] 📍 Обработка завершена\n")

    def _restart_emulator(self, emulator) -> bool:
        """
        Перезапуск эмулятора (остановка + запуск)

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если перезапуск успешен
        """
        emulator_name = emulator.get('name', 'Unknown')

        logger.info(f"[{emulator_name}] 🔄 Перезапуск эмулятора...")

        # Остановка
        logger.info(f"[{emulator_name}] Остановка...")
        stop_success = self.emulator_manager.stop_emulator(emulator['id'])
        if not stop_success:
            logger.warning(f"[{emulator_name}] ⚠️ Проблема при остановке, продолжаю...")

        # Пауза между остановкой и запуском
        time.sleep(5)

        # Запуск
        logger.info(f"[{emulator_name}] Запуск...")
        start_success = self.emulator_manager.start_emulator(emulator['id'])
        if not start_success:
            logger.error(f"[{emulator_name}] ❌ Не удалось запустить эмулятор")
            return False

        # Ожидание ADB
        logger.info(f"[{emulator_name}] Ожидание ADB...")
        adb_ready = wait_for_adb(emulator['port'], timeout=90)

        if not adb_ready:
            logger.error(f"[{emulator_name}] ❌ ADB не готов после перезапуска")
            return False

        logger.success(f"[{emulator_name}] ✅ Перезапуск успешен")
        return True

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