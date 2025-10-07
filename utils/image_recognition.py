"""
Распознавание изображений через OpenCV
"""

import os
import cv2
import numpy as np
from utils.adb_controller import execute_command
from utils.logger import logger


def find_image(emulator, template_path, threshold=0.8):
    """
    Поиск изображения на экране эмулятора

    Args:
        emulator: объект эмулятора (с полями id, name, port)
        template_path: путь к шаблону (например "data/templates/game_loading/popup_close.png")
        threshold: порог совпадения (0.0 - 1.0), по умолчанию 0.8

    Returns:
        tuple: (x, y) координаты центра найденного изображения или None если не найдено

    Note:
        Разрешение экрана эмулятора: 540x960, DPI 240
    """

    # 1. Проверить существование шаблона
    if not os.path.exists(template_path):
        logger.error(f"Шаблон не найден: {template_path}")
        return None

    # 2. Получить скриншот экрана эмулятора
    screenshot = get_screenshot(emulator)

    if screenshot is None:
        logger.error(f"Не удалось получить скриншот эмулятора {emulator['name']}")
        return None

    # 3. Загрузить шаблон
    template = cv2.imread(template_path)

    if template is None:
        logger.error(f"Не удалось загрузить шаблон: {template_path}")
        return None

    # 4. Проверить размеры (шаблон не должен быть больше скриншота)
    if template.shape[0] > screenshot.shape[0] or template.shape[1] > screenshot.shape[1]:
        logger.error(f"Шаблон больше скриншота: {template_path}")
        return None

    # 5. Поиск шаблона на скриншоте
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    # 6. Проверка порога совпадения
    if max_val >= threshold:
        # Найдено - вычислить координаты центра
        h, w = template.shape[:2]
        center_x = max_loc[0] + w // 2
        center_y = max_loc[1] + h // 2

        logger.debug(f"Изображение найдено: {os.path.basename(template_path)} в ({center_x}, {center_y}), совпадение: {max_val:.2f}")
        return (center_x, center_y)
    else:
        logger.debug(f"Изображение не найдено: {os.path.basename(template_path)} (лучшее совпадение: {max_val:.2f}, порог: {threshold})")
        return None


def get_screenshot(emulator):
    """
    Получает скриншот экрана эмулятора

    Args:
        emulator: объект эмулятора (с полями id, name, port)

    Returns:
        numpy.ndarray: Скриншот в формате OpenCV (BGR) или None при ошибке
    """

    # Импортируем здесь чтобы избежать циклических зависимостей
    from utils.adb_controller import execute_command, get_adb_device

    # Создать папку для скриншотов если не существует
    os.makedirs("data/screenshots", exist_ok=True)

    # Получить правильный ADB адрес
    adb_address = get_adb_device(emulator['port'])

    # Путь для сохранения скриншота
    screenshot_path = f"data/screenshots/{emulator['id']}.png"

    try:
        # 1. Сделать скриншот на устройстве
        cmd_screencap = f"adb -s {adb_address} shell screencap -p /sdcard/screenshot.png"
        execute_command(cmd_screencap)

        # 2. Скачать скриншот с устройства
        cmd_pull = f"adb -s {adb_address} pull /sdcard/screenshot.png {screenshot_path}"
        result = execute_command(cmd_pull)

        # Проверить успешность скачивания
        if "error" in result.lower() or not os.path.exists(screenshot_path):
            logger.error(f"Не удалось скачать скриншот для {emulator['name']}")
            return None

        # 3. Загрузить скриншот в OpenCV
        screenshot = cv2.imread(screenshot_path)

        if screenshot is None:
            logger.error(f"Не удалось загрузить скриншот: {screenshot_path}")
            return None

        logger.debug(f"Скриншот получен: {emulator['name']} ({screenshot.shape[1]}x{screenshot.shape[0]})")
        return screenshot

    except Exception as e:
        logger.error(f"Ошибка при получении скриншота {emulator['name']}: {e}")
        return None