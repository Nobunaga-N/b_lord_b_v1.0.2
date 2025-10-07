"""
Контроллер процесса бота
"""

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
        Остановка бота

        Returns:
            bool: True если остановка успешна, False если ошибка
        """

        # Проверка что бот запущен
        if not self.orchestrator or not self.orchestrator.is_running:
            logger.warning("Бот не запущен")
            return False

        try:
            logger.info("Остановка бота...")

            # Остановить оркестратор (graceful shutdown)
            self.orchestrator.stop()

            logger.success("Бот успешно остановлен")
            return True

        except Exception as e:
            logger.error(f"Ошибка при остановке бота: {e}")
            logger.exception(e)
            return False

    def is_running(self):
        """
        Проверяет запущен ли бот

        Returns:
            bool: True если бот запущен
        """
        return self.orchestrator and self.orchestrator.is_running