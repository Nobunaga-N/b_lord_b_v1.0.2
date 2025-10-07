"""
Запуск игры и ожидание загрузки
"""

import time
from utils.adb_controller import launch_app, press_key
from utils.image_recognition import find_image
from utils.logger import logger


class GameLauncher:
    """Запуск Beast Lord и ожидание полной загрузки"""

    # Константы
    PACKAGE_NAME = "com.allstarunion.beastlord"
    LOADING_SCREEN_TEMPLATE = "data/templates/game_loading/loading_screen.png"
    POPUP_CLOSE_TEMPLATE = "data/templates/game_loading/popup_close.png"
    WORLD_MAP_TEMPLATE = "data/templates/game_loading/world_map.png"

    def __init__(self, emulator):
        """
        Инициализация GameLauncher

        Args:
            emulator: словарь с данными эмулятора (id, name, port)
        """
        self.emulator = emulator
        self.emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

    def launch_and_wait(self):
        """
        Запускает игру Beast Lord и ожидает полной загрузки

        Returns:
            bool: True если игра загрузилась успешно, False если ошибка

        Алгоритм:
        1. Запустить игру через ADB
        2. Ждать пока пропадет загрузочный экран (до 60 сек)
        3. Ждать 4 секунды для полной загрузки
        4. Цикл поиска popup и карты мира (макс 10 попыток):
           - Если popup → нажать ESC, ждать 2 сек
           - Если карта мира → готово
           - Иначе → ждать 2 сек, повторить
        """

        logger.info(f"[{self.emulator_name}] Запуск игры Beast Lord...")

        # ===== ШАГ 1: Запустить игру =====
        if not self._launch_game():
            return False

        # ===== ШАГ 2: Ожидание пока пропадет загрузочный экран =====
        if not self._wait_loading_screen_disappear():
            return False

        # ===== ШАГ 3: Ждем 4 секунды для полной загрузки =====
        logger.info(f"[{self.emulator_name}] Ожидание 4 секунды для загрузки...")
        time.sleep(4)

        # ===== ШАГ 4: Цикл поиска popup и карты мира =====
        if not self._wait_for_world_map():
            return False

        logger.success(f"[{self.emulator_name}] Игра загружена успешно!")
        return True

    def _launch_game(self):
        """
        Запускает игру через ADB

        Returns:
            bool: True если запуск успешен
        """
        from utils.adb_controller import get_adb_device, execute_command

        # Получить ADB адрес
        adb_address = get_adb_device(self.emulator['port'])

        # Команда запуска с явным указанием Activity
        command = f"adb -s {adb_address} shell am start -n {self.PACKAGE_NAME}/.MainActivity"

        logger.info(f"[{self.emulator_name}] Запуск игры...")
        result = execute_command(command)

        # Логируем результат команды
        logger.debug(f"[{self.emulator_name}] Результат запуска: {result.strip()[:200]}")

        # Проверка ошибок
        if "Error" in result or "error" in result.lower():
            logger.error(f"[{self.emulator_name}] Ошибка при запуске игры: {result}")
            return False

        # Проверка успешности запуска
        if "Starting: Intent" in result:
            logger.success(f"[{self.emulator_name}] Команда запуска выполнена успешно")
            return True
        else:
            logger.error(f"[{self.emulator_name}] Неожиданный результат запуска игры")
            return False

    def _wait_loading_screen_disappear(self, timeout=60):
        """
        Ожидает пока пропадет загрузочный экран

        Args:
            timeout: максимальное время ожидания (по умолчанию 60 сек)

        Returns:
            bool: True если загрузочный экран пропал, False если таймаут
        """

        logger.info(f"[{self.emulator_name}] Ожидание загрузочного экрана...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Проверяем есть ли загрузочный экран
            loading_found = find_image(
                self.emulator,
                self.LOADING_SCREEN_TEMPLATE,
                threshold=0.8
            )

            if loading_found:
                # Загрузочный экран еще есть - ждем
                logger.debug(f"[{self.emulator_name}] Загрузочный экран виден, ожидание...")
                time.sleep(2)
            else:
                # Загрузочный экран пропал
                logger.info(f"[{self.emulator_name}] Загрузочный экран пропал")
                return True

        # Таймаут
        logger.error(f"[{self.emulator_name}] Таймаут ожидания загрузочного экрана ({timeout}s)")
        return False

    def _wait_for_world_map(self, max_attempts=10):
        """
        Цикл поиска popup и карты мира

        Args:
            max_attempts: максимальное количество попыток (по умолчанию 10)

        Returns:
            bool: True если карта мира найдена, False если не найдена за max_attempts
        """

        logger.info(f"[{self.emulator_name}] Поиск карты мира и popup окон...")

        for attempt in range(1, max_attempts + 1):
            logger.debug(f"[{self.emulator_name}] Попытка {attempt}/{max_attempts}")

            # Проверяем popup и карту мира ОДНОВРЕМЕННО
            popup_found = find_image(
                self.emulator,
                self.POPUP_CLOSE_TEMPLATE,
                threshold=0.8
            )

            map_found = find_image(
                self.emulator,
                self.WORLD_MAP_TEMPLATE,
                threshold=0.8
            )

            # Если нашли popup - закрываем
            if popup_found:
                logger.warning(f"[{self.emulator_name}] Обнаружено всплывающее окно, закрываю...")
                press_key(self.emulator, "ESC")
                time.sleep(2)
                continue  # Повторяем цикл

            # Если нашли карту мира - готово
            if map_found:
                logger.success(f"[{self.emulator_name}] Карта мира обнаружена, игра готова")
                return True

            # Ничего не найдено - ждем и повторяем
            logger.debug(f"[{self.emulator_name}] Popup и карта не найдены, ожидание 2 сек...")
            time.sleep(2)

        # Не нашли карту мира за max_attempts попыток
        logger.error(f"[{self.emulator_name}] Не удалось дождаться карты мира за {max_attempts} попыток")
        return False