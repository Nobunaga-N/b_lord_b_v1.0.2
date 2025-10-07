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
        2. Ждать появления и исчезновения загрузочного экрана (с паузой 2 сек)
        3. Цикл поиска popup и карты мира (макс 10 попыток):
           - Если popup → нажать ESC, ждать 2 сек
           - Если карта мира → готово
           - Иначе → ждать 2 сек, повторить
        """

        logger.info(f"[{self.emulator_name}] Запуск игры Beast Lord...")

        # ===== ШАГ 1: Запустить игру =====
        if not self._launch_game():
            return False

        # ===== ШАГ 2: Ожидание появления и исчезновения загрузочного экрана =====
        # (внутри метода уже есть пауза 2 сек после исчезновения)
        if not self._wait_loading_screen_disappear():
            return False

        # ===== ШАГ 3: Цикл поиска popup и карты мира =====
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
        Ожидает появления и исчезновения загрузочного экрана

        Алгоритм:
        1. ФАЗА 1: Ждем появления загрузочного экрана (макс timeout секунд)
           - Скриншот каждые 1.5 секунды
           - Как только найден → переходим к фазе 2
        2. ФАЗА 2: Ждем исчезновения загрузочного экрана (макс timeout секунд)
           - Скриншот каждые 1.5 секунды
           - Как только пропал → возвращаем True
        3. Пауза 2 секунды после исчезновения

        Args:
            timeout: максимальное время ожидания для каждой фазы в секундах

        Returns:
            bool: True если экран появился и исчез, False если таймаут
        """

        screen_check_interval = 1.5  # Интервал проверки в секундах

        # ===== ФАЗА 1: Ожидание ПОЯВЛЕНИЯ загрузочного экрана =====
        logger.info(f"[{self.emulator_name}] ФАЗА 1: Ожидание появления загрузочного экрана...")
        start_time = time.time()
        loading_appeared = False

        while time.time() - start_time < timeout:
            elapsed = int(time.time() - start_time)

            # Проверяем наличие загрузочного экрана
            loading_found = find_image(
                self.emulator,
                self.LOADING_SCREEN_TEMPLATE,
                threshold=0.8,
                debug_name="loading_appear"
            )

            if loading_found:
                logger.success(f"[{self.emulator_name}] ✓ Загрузочный экран появился ({elapsed}s)")
                loading_appeared = True
                break

            logger.debug(f"[{self.emulator_name}] Загрузочный экран не виден, ожидание... ({elapsed}s/{timeout}s)")
            time.sleep(screen_check_interval)

        if not loading_appeared:
            logger.error(f"[{self.emulator_name}] ✗ Таймаут: загрузочный экран не появился за {timeout}s")
            logger.warning(f"[{self.emulator_name}] Возможно игра зависла, требуется перезапуск эмулятора")
            return False

        # ===== ФАЗА 2: Ожидание ИСЧЕЗНОВЕНИЯ загрузочного экрана =====
        logger.info(f"[{self.emulator_name}] ФАЗА 2: Ожидание исчезновения загрузочного экрана...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            elapsed = int(time.time() - start_time)

            # Проверяем наличие загрузочного экрана
            loading_found = find_image(
                self.emulator,
                self.LOADING_SCREEN_TEMPLATE,
                threshold=0.8,
                debug_name="loading_disappear"
            )

            if loading_found:
                logger.debug(f"[{self.emulator_name}] Загрузочный экран еще виден, ожидание... ({elapsed}s/{timeout}s)")
                time.sleep(screen_check_interval)
            else:
                logger.success(f"[{self.emulator_name}] ✓ Загрузочный экран исчез ({elapsed}s)")

                # Пауза 2 секунды после исчезновения
                logger.info(f"[{self.emulator_name}] Пауза 2 секунды после исчезновения экрана...")
                time.sleep(2)

                return True

        # Таймаут фазы 2
        logger.error(f"[{self.emulator_name}] ✗ Таймаут: загрузочный экран не исчез за {timeout}s")
        logger.warning(f"[{self.emulator_name}] Возможно игра зависла, требуется перезапуск эмулятора")
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
            popup_coords = find_image(
                self.emulator,
                self.POPUP_CLOSE_TEMPLATE,
                threshold=0.8,
                debug_name=f"popup_attempt{attempt}"
            )

            map_coords = find_image(
                self.emulator,
                self.WORLD_MAP_TEMPLATE,
                threshold=0.95,  # Повышен порог для карты мира
                debug_name=f"map_attempt{attempt}"
            )

            # Если нашли popup - закрываем через ESC
            if popup_coords:
                logger.warning(f"[{self.emulator_name}] Обнаружено всплывающее окно, закрываю через ESC...")
                press_key(self.emulator, "ESC")
                time.sleep(2)
                continue  # Повторяем цикл

            # Если нашли карту мира - готово
            if map_coords:
                logger.success(f"[{self.emulator_name}] ✓ Карта мира обнаружена, игра готова")
                return True

            # Ничего не найдено - ждем и повторяем
            logger.debug(f"[{self.emulator_name}] Popup и карта не найдены, ожидание 2 сек...")
            time.sleep(2)

        # Не нашли карту мира за max_attempts попыток
        logger.error(f"[{self.emulator_name}] ✗ Не удалось дождаться карты мира за {max_attempts} попыток")
        return False