"""
Главный оркестратор бота Beast Lord Bot v3.0
С интегрированным планировщиком (Scheduler)

ПЕРЕРАБОТАН: Бесконечный цикл с мониторингом таймеров,
батчингом событий и приоритизацией эмуляторов.

Версия: 2.0
Дата создания: 2025-01-06
Последнее обновление: 2025-02-11 (интеграция планировщика)
"""

import time
import threading
from datetime import datetime
from utils.logger import logger
from utils.config_manager import load_config
from utils.adb_controller import wait_for_adb
from utils.recovery_manager import recovery_manager
from core.emulator_manager import EmulatorManager
from core.game_launcher import GameLauncher
from core.function_executor import execute_functions, FUNCTION_CLASSES


class BotOrchestrator:
    """
    Управление главным циклом бота с интегрированным планировщиком

    Основные возможности:
    - Бесконечный цикл с мониторингом готовности эмуляторов
    - Лёгкие проверки через БД (без запуска эмуляторов)
    - Батчинг событий (ожидание нескольких строителей перед запуском)
    - Приоритизация: новые эмуляторы → просроченные → запланированные
    - Умное ожидание (сон до ближайшего события)
    - Динамическое подхватывание новых/удалённых эмуляторов
    - Graceful shutdown без зависаний
    - Данные расписания для GUI
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
        self.active_slots = []       # [(emulator, thread), ...]
        self.max_concurrent = 3
        self.processing_ids = set()  # ID эмуляторов в обработке

        # Настройки планировщика (из конфига)
        scheduler_config = self._load_scheduler_config()
        self.batch_window = scheduler_config.get('batch_window', 300)
        self.check_interval = scheduler_config.get('check_interval', 60)

        # Данные расписания (для GUI, thread-safe)
        self.schedule_data = []
        self.schedule_lock = threading.Lock()

        # Компоненты
        self.emulator_manager = EmulatorManager()

        logger.debug(f"BotOrchestrator инициализирован "
                     f"(batch_window={self.batch_window}с, check_interval={self.check_interval}с)")

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
            self.thread.join()

        # 3. Дождаться завершения всех активных потоков
        for emulator, thread in self.active_slots[:]:
            if thread.is_alive():
                logger.info(f"Ожидание завершения: {emulator['name']}...")
                thread.join()

        # 4. Принудительно закрыть все эмуляторы (на всякий случай)
        for emulator, _ in self.active_slots:
            logger.info(f"Закрытие эмулятора: {emulator['name']}")
            self.emulator_manager.stop_emulator(emulator['id'])

        # 5. Очистить данные
        self.active_slots = []
        self.processing_ids.clear()

        # 6. Очистить расписание
        with self.schedule_lock:
            self.schedule_data = []

        logger.success("Бот остановлен")
        self._update_gui()

    # ===== ГЛАВНЫЙ ЦИКЛ ПЛАНИРОВЩИКА =====

    def _main_loop(self):
        """
        Главный цикл планировщика (бесконечный)

        Алгоритм:
        1. Загрузить/обновить конфиг (подхватить новые эмуляторы)
        2. Очистить завершённые слоты
        3. Рассчитать расписание для всех эмуляторов
        4. Запустить готовые (до max_concurrent)
        5. Умное ожидание до ближайшего события
        6. Повторить
        """
        try:
            logger.info("🔄 Планировщик запущен")

            while self.is_running:

                # 1. Загрузить актуальный конфиг
                #    (подхватит новые эмуляторы, изменения функций)
                enabled_emulators, self.max_concurrent, active_functions = self._load_config()

                if not enabled_emulators:
                    logger.warning("Нет включённых эмуляторов, ожидание...")
                    self._sleep_interruptible(self.check_interval)
                    continue

                if not active_functions:
                    logger.warning("Нет активных функций, ожидание...")
                    self._sleep_interruptible(self.check_interval)
                    continue

                # 2. Очистить завершённые слоты
                self._cleanup_finished_slots()

                # 3. Проверить запросы на перезапуск
                self._check_restart_requests()

                # 4. Рассчитать расписание
                schedule = self._build_schedule(enabled_emulators, active_functions)

                # 5. Обновить данные расписания для GUI
                self._update_schedule_data(schedule, enabled_emulators)

                # 6. Запустить готовые эмуляторы
                now = datetime.now()
                launched = 0

                for launch_time, emulator, reasons in schedule:
                    if not self.is_running:
                        break
                    if len(self.active_slots) >= self.max_concurrent:
                        break
                    if launch_time > now:
                        break  # Остальные ещё не готовы (список отсортирован)

                    # Запуск в потоке
                    thread = threading.Thread(
                        target=self._process_emulator,
                        args=(emulator, active_functions),
                        daemon=False
                    )
                    thread.start()

                    self.active_slots.append((emulator, thread))
                    self.processing_ids.add(emulator['id'])
                    launched += 1

                    logger.info(
                        f"🚀 {emulator['name']} → слот "
                        f"{len(self.active_slots)}/{self.max_concurrent} "
                        f"(причины: {', '.join(reasons)})"
                    )

                self._update_gui()

                if launched > 0:
                    logger.info(f"📊 Запущено: {launched}, "
                                f"активно: {len(self.active_slots)}/{self.max_concurrent}")

                # 7. Умное ожидание
                sleep_seconds = self._calculate_sleep_time(schedule)
                logger.debug(f"💤 Следующая проверка через {sleep_seconds}с")
                self._sleep_interruptible(sleep_seconds)

            # Завершение
            self._wait_all_slots_finish()
            logger.info("🔄 Планировщик остановлен")
            self.is_running = False
            self._update_gui()

        except Exception as e:
            logger.error(f"Критическая ошибка в планировщике: {e}")
            logger.exception(e)
            self.is_running = False
            self._update_gui()

    # ===== ЛОГИКА РАСПИСАНИЯ =====

    def _build_schedule(self, enabled_emulators, active_functions):
        """
        Рассчитать расписание запуска для всех эмуляторов

        Для каждого эмулятора:
        1. Собрать события от всех включённых функций (get_next_event_time)
        2. Рассчитать оптимальное время с батчингом
        3. Отсортировать по приоритету

        Args:
            enabled_emulators: список словарей эмуляторов
            active_functions: список имён активных функций

        Returns:
            list[(datetime, emulator_dict, list[str])]
            Каждый элемент: (оптимальное_время_запуска, эмулятор, причины)
            Отсортировано по времени (datetime.min первые)
        """
        schedule = []

        for emu in enabled_emulators:
            emu_id = emu['id']

            # Пропустить уже обрабатываемые
            if emu_id in self.processing_ids:
                continue

            # Собрать события от всех функций
            events = []  # [(datetime, func_name), ...]

            for func_name in active_functions:
                func_class = FUNCTION_CLASSES.get(func_name)
                if not func_class:
                    continue

                try:
                    event_time = func_class.get_next_event_time(emu_id)
                    if event_time is not None:
                        events.append((event_time, func_name))
                except Exception as e:
                    logger.error(f"Ошибка get_next_event_time для {func_name} "
                                 f"(emu {emu_id}): {e}")

            if not events:
                continue  # Нечего делать на этом эмуляторе

            # Рассчитать оптимальное время с батчингом
            launch_time, reasons = self._calculate_optimal_launch(events)
            schedule.append((launch_time, emu, reasons))

        # Сортировка: datetime.min первые, потом по времени
        schedule.sort(key=lambda x: x[0])

        return schedule

    def _calculate_optimal_launch(self, events):
        """
        Рассчитать оптимальное время запуска с учётом батчинга

        Батчинг: если несколько событий происходят в пределах batch_window,
        ждём последнее из них чтобы обработать всё за один запуск.

        Пример (batch_window=300с):
          Строитель 1: 14:00
          Строитель 2: 14:03 (в пределах 5 мин от 14:00 → ждём)
          Строитель 3: 14:45 (за пределами → не ждём)
          Результат: оптимальное время = 14:03

        Args:
            events: [(datetime, func_name), ...] — события от функций

        Returns:
            (optimal_datetime, list[str]) — время и список причин
        """
        events.sort(key=lambda x: x[0])

        base_time = events[0][0]
        reasons = [events[0][1]]

        # Если первое событие — datetime.min (новый эмулятор)
        if base_time == datetime.min:
            reasons = [f"{e[1]}(новый)" for e in events]
            return datetime.min, reasons

        # Батчинг: расширяем окно пока события в пределах batch_window
        optimal_time = base_time

        for event_time, func_name in events[1:]:
            delta = (event_time - optimal_time).total_seconds()

            if delta <= 0:
                # Событие уже просрочено или одновременно — включаем
                reasons.append(func_name)
            elif delta <= self.batch_window:
                # В пределах окна — ждём и включаем
                optimal_time = event_time
                reasons.append(func_name)
            # else: слишком далеко — не ждём

        return optimal_time, reasons

    def _calculate_sleep_time(self, schedule):
        """
        Рассчитать время сна до ближайшего будущего события

        Если все события в прошлом или нет событий — спим check_interval.
        Если есть будущие события — спим до ближайшего (но не больше check_interval).

        Args:
            schedule: результат _build_schedule()

        Returns:
            int — секунды (от 1 до check_interval)
        """
        now = datetime.now()

        for launch_time, emu, reasons in schedule:
            if launch_time > now:
                wait = (launch_time - now).total_seconds()
                return max(1, min(int(wait), self.check_interval))

        # Нет будущих событий
        return self.check_interval

    def _sleep_interruptible(self, seconds):
        """
        Сон с проверкой is_running каждую секунду

        Позволяет быстро реагировать на stop() даже при длительном ожидании.

        Args:
            seconds: сколько секунд спать (максимум)
        """
        for _ in range(int(seconds)):
            if not self.is_running:
                break
            time.sleep(1)

    # ===== УПРАВЛЕНИЕ СЛОТАМИ =====

    def _cleanup_finished_slots(self):
        """Очистить завершённые потоки из active_slots"""
        for emulator, thread in self.active_slots[:]:
            if not thread.is_alive():
                logger.success(f"✅ Слот освобожден: {emulator['name']}")
                self.active_slots.remove((emulator, thread))
                self.processing_ids.discard(emulator['id'])
        self._update_gui()

    def _wait_all_slots_finish(self):
        """Дождаться завершения всех активных потоков при остановке"""
        for emulator, thread in self.active_slots[:]:
            if thread.is_alive():
                logger.info(f"Ожидание завершения: {emulator['name']}...")
                thread.join()

        # Принудительно закрыть все эмуляторы
        for emulator, _ in self.active_slots:
            try:
                self.emulator_manager.stop_emulator(emulator['id'])
            except Exception as e:
                logger.error(f"Ошибка при закрытии {emulator['name']}: {e}")

        self.active_slots = []
        self.processing_ids.clear()

    # ===== ОБРАБОТКА ЭМУЛЯТОРА (БЕЗ ИЗМЕНЕНИЙ) =====

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

            # Проверка запроса на перезапуск
            if recovery_manager.has_restart_request(emulator_id):
                reason = recovery_manager.get_restart_reason(emulator_id)
                logger.warning(f"[{emulator_name}] 🔄 Обнаружен запрос на перезапуск: {reason}")

                success = self._restart_emulator(emulator)

                if success:
                    logger.success(f"[{emulator_name}] ✅ Эмулятор успешно перезапущен")
                    recovery_manager.clear_restart_request(emulator_id)
                else:
                    logger.error(f"[{emulator_name}] ❌ Не удалось перезапустить эмулятор")
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
                self.emulator_manager.stop_emulator(emulator_id)
                return

            # 3. Запустить игру и дождаться загрузки
            game_launcher = GameLauncher(emulator)
            if not game_launcher.launch_and_wait():
                logger.error(f"[{emulator_name}] ❌ Игра не загрузилась")
                recovery_manager.handle_stuck_state(emulator, context="Игра не загрузилась")
                self.emulator_manager.stop_emulator(emulator_id)
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
                recovery_manager.handle_stuck_state(emulator, context=f"Ошибка функций: {func_error}")

        except Exception as e:
            logger.error(f"[{emulator_name}] ❌ Критическая ошибка в обработке: {e}")
            logger.exception(e)
            recovery_manager.handle_stuck_state(emulator, context=f"Критическая ошибка: {e}")

        finally:
            # Всегда закрыть эмулятор
            logger.info(f"[{emulator_name}] Закрытие эмулятора...")
            try:
                self.emulator_manager.stop_emulator(emulator_id)
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

    # ===== ДАННЫЕ РАСПИСАНИЯ ДЛЯ GUI =====

    def _update_schedule_data(self, schedule, enabled_emulators):
        """
        Обновить данные расписания для окна GUI (thread-safe)

        Формирует полную картину:
        - Активные слоты (в обработке)
        - Очередь (готовые + запланированные)
        - Эмуляторы без задач

        Args:
            schedule: результат _build_schedule()
            enabled_emulators: все включённые эмуляторы
        """
        now = datetime.now()

        # Собираем данные по категориям
        active = []
        queue = []
        idle_count = 0

        # Активные слоты
        for emu, thread in self.active_slots:
            active.append({
                "emulator_id": emu['id'],
                "emulator_name": emu['name'],
                "status": "processing"
            })

        # Очередь из расписания
        for launch_time, emu, reasons in schedule:
            if launch_time == datetime.min:
                status = "new"
                time_str = "СЕЙЧАС"
                wait_minutes = 0
            elif launch_time <= now:
                status = "ready"
                time_str = "ГОТОВ"
                wait_minutes = 0
            else:
                status = "waiting"
                time_str = launch_time.strftime("%H:%M")
                wait_minutes = int((launch_time - now).total_seconds() / 60)

            queue.append({
                "emulator_id": emu['id'],
                "emulator_name": emu['name'],
                "launch_time": time_str,
                "wait_minutes": wait_minutes,
                "reasons": reasons,
                "status": status
            })

        # Считаем эмуляторы без задач
        scheduled_ids = self.processing_ids | {emu['id'] for _, emu, _ in schedule}
        idle_count = sum(1 for emu in enabled_emulators if emu['id'] not in scheduled_ids)

        with self.schedule_lock:
            self.schedule_data = {
                "active": active,
                "queue": queue,
                "idle_count": idle_count,
                "total_enabled": len(enabled_emulators),
                "max_concurrent": self.max_concurrent,
                "updated_at": now.strftime("%H:%M:%S")
            }

    def get_schedule_snapshot(self):
        """
        Получить снимок расписания для GUI (thread-safe)

        Returns:
            dict с ключами: active, queue, idle_count, total_enabled,
                           max_concurrent, updated_at
        """
        with self.schedule_lock:
            if isinstance(self.schedule_data, dict):
                return self.schedule_data.copy()
            return {
                "active": [],
                "queue": [],
                "idle_count": 0,
                "total_enabled": 0,
                "max_concurrent": self.max_concurrent,
                "updated_at": ""
            }

    # ===== КОНФИГУРАЦИЯ =====

    def _load_config(self):
        """
        Загружает конфигурацию бота

        Returns:
            tuple: (enabled_emulators, max_concurrent, active_functions)
        """
        # Загрузить gui_config.yaml
        gui_config = load_config("configs/gui_config.yaml", silent=True)

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
        emulators_config = load_config("configs/emulators.yaml", silent=True)

        if not emulators_config or 'emulators' not in emulators_config:
            return [], max_concurrent, active_functions

        all_emulators = emulators_config['emulators']

        # Фильтровать только включенные
        enabled_emulators = [emu for emu in all_emulators if emu['id'] in enabled_ids]

        return enabled_emulators, max_concurrent, active_functions

    def _load_scheduler_config(self):
        """
        Загрузить настройки планировщика из bot_config.yaml

        Returns:
            dict: настройки планировщика
        """
        config = load_config("configs/bot_config.yaml", silent=True)
        return config.get('scheduler', {})

    # ===== ОБНОВЛЕНИЕ GUI =====

    def _update_gui(self):
        """Обновляет GUI через callback"""

        if not self.gui_callback:
            return

        bot_state = {
            "is_running": self.is_running,
            "active_count": len(self.active_slots),
            "max_concurrent": self.max_concurrent,
            "active_emulators": [
                {"id": emu['id'], "name": emu['name']}
                for emu, _ in self.active_slots
            ],
            "schedule_count": len(self.schedule_data.get('queue', []))
            if isinstance(self.schedule_data, dict) else 0,
        }

        try:
            self.gui_callback(bot_state)
        except Exception as e:
            logger.error(f"Ошибка при обновлении GUI: {e}")