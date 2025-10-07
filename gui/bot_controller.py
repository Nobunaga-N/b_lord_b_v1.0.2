"""
Контроллер процесса бота
"""

import threading
from core.bot_orchestrator import BotOrchestrator
from utils.logger import logger, open_log_terminal


class BotController:
    """Управление запуском/остановкой бота"""

    def __init__(self, gui_callback=None):
        """
        Инициализация контроллера

        Args:
            gui_callback: функция для обновления GUI статуса
                         Формат: callback(bot_state)
        """
        self.gui_callback = gui_callback
        self.orchestrator = None
        self.stop_thread = None  # Поток для асинхронной остановки

        logger.debug("BotController инициализирован")

    def start(self):
        """
        Запуск бота

        Returns:
            bool: True если запуск успешен, False если ошибка
        """

        # Проверка что бот не запущен
        if self.orchestrator and self.orchestrator.is_running:
            logger.warning("Бот уже запущен")
            return False

        try:
            logger.info("Запуск бота...")

            # 1. Открыть Windows Terminal с логами
            logger.info("Открытие терминала с логами...")
            open_log_terminal()

            # 2. Создать новый экземпляр оркестратора
            self.orchestrator = BotOrchestrator(gui_callback=self.gui_callback)

            # 3. Запустить бота
            success = self.orchestrator.start()

            if success:
                logger.success("Бот успешно запущен")
                return True
            else:
                logger.error("Не удалось запустить бота")
                return False

        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
            logger.exception(e)
            return False

    def stop(self):
        """
        Остановка бота (асинхронная, не блокирует GUI)

        Returns:
            bool: True если остановка начата успешно, False если ошибка
        """

        # Проверка что бот запущен
        if not self.orchestrator or not self.orchestrator.is_running:
            logger.warning("Бот не запущен")
            return False

        # Проверка что остановка уже не выполняется
        if self.stop_thread and self.stop_thread.is_alive():
            logger.warning("Остановка уже выполняется")
            return False

        try:
            logger.info("Запуск асинхронной остановки бота...")

            # ИСПРАВЛЕНИЕ: Запускаем остановку в отдельном потоке
            self.stop_thread = threading.Thread(
                target=self._stop_async,
                daemon=False
            )
            self.stop_thread.start()

            logger.info("Остановка запущена (выполняется в фоне, GUI не блокируется)")
            return True

        except Exception as e:
            logger.error(f"Ошибка при запуске остановки бота: {e}")
            logger.exception(e)
            return False

    def _stop_async(self):
        """
        Внутренний метод для остановки в отдельном потоке

        Выполняется асинхронно, не блокирует GUI
        """
        try:
            logger.info("Асинхронная остановка: начало...")

            # Остановить оркестратор (graceful shutdown)
            # Это может занять время, но GUI не зависнет
            self.orchestrator.stop()

            logger.success("Бот успешно остановлен (асинхронная остановка завершена)")

        except Exception as e:
            logger.error(f"Ошибка в асинхронной остановке: {e}")
            logger.exception(e)

    def is_running(self):
        """
        Проверяет запущен ли бот

        Returns:
            bool: True если бот запущен
        """
        return self.orchestrator and self.orchestrator.is_running