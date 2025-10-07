"""
Распознавание изображений через OpenCV
"""

import os
import cv2
import numpy as np
from utils.adb_controller import execute_command
from utils.logger import logger


# DEBUG режим - сохранять скриншоты с отметками
DEBUG_MODE = True  # Установить False для отключения


def find_image(emulator, template_path, threshold=0.8, debug_name=None):
    """
    Поиск изображения на экране эмулятора

    Args:
        emulator: объект эмулятора (с полями id, name, port)
        template_path: путь к шаблону (например "data/templates/game_loading/popup_close.png")
        threshold: порог совпадения (0.0 - 1.0), по умолчанию 0.8
        debug_name: название для debug скриншота (опционально)

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

    # 6. Debug режим - сохранить скриншот с отметкой
    if DEBUG_MODE:
        _save_debug_screenshot(
            screenshot=screenshot,
            template=template,
            template_name=os.path.basename(template_path),
            match_location=max_loc,
            match_value=max_val,
            threshold=threshold,
            emulator_id=emulator['id'],
            found=(max_val >= threshold),
            debug_name=debug_name
        )

    # 7. Проверка порога совпадения
    if max_val >= threshold:
        # Найдено - вычислить координаты центра
        h, w = template.shape[:2]
        center_x = max_loc[0] + w // 2
        center_y = max_loc[1] + h // 2

        logger.success(f"✓ {os.path.basename(template_path)} найден в ({center_x}, {center_y}), совпадение: {max_val:.3f}")
        return (center_x, center_y)
    else:
        logger.debug(f"✗ {os.path.basename(template_path)} не найден (лучшее: {max_val:.3f}, порог: {threshold})")
        return None


def _save_debug_screenshot(screenshot, template, template_name, match_location,
                           match_value, threshold, emulator_id, found, debug_name=None):
    """
    Сохраняет debug скриншот с отметкой найденной области

    Args:
        screenshot: скриншот экрана
        template: шаблон для поиска
        template_name: название шаблона
        match_location: координаты левого верхнего угла найденной области
        match_value: значение совпадения (0.0-1.0)
        threshold: порог для срабатывания
        emulator_id: ID эмулятора
        found: True если изображение найдено (совпадение >= threshold)
        debug_name: кастомное имя для файла
    """
    try:
        # Создать папку для debug скриншотов
        debug_folder = "data/screenshots/debug"
        os.makedirs(debug_folder, exist_ok=True)

        # Копировать скриншот для рисования
        debug_img = screenshot.copy()

        # Параметры шаблона
        h, w = template.shape[:2]
        top_left = match_location
        bottom_right = (top_left[0] + w, top_left[1] + h)
        center = (top_left[0] + w // 2, top_left[1] + h // 2)

        # Цвет рамки (зеленый если найдено, красный если нет)
        color = (0, 255, 0) if found else (0, 0, 255)
        thickness = 3 if found else 2

        # Нарисовать прямоугольник
        cv2.rectangle(debug_img, top_left, bottom_right, color, thickness)

        # Нарисовать крестик в центре
        cross_size = 10
        cv2.line(debug_img,
                (center[0] - cross_size, center[1]),
                (center[0] + cross_size, center[1]),
                color, thickness)
        cv2.line(debug_img,
                (center[0], center[1] - cross_size),
                (center[0], center[1] + cross_size),
                color, thickness)

        # Добавить текст с информацией
        status = "FOUND" if found else "NOT FOUND"
        text = f"{template_name}: {status} ({match_value:.3f})"

        # Фон для текста (для читаемости)
        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
        cv2.rectangle(debug_img,
                     (10, 10),
                     (20 + text_size[0], 40 + text_size[1]),
                     (0, 0, 0),
                     -1)

        # Сам текст
        cv2.putText(debug_img, text, (15, 35),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # Имя файла
        if debug_name:
            filename = f"emu{emulator_id}_{debug_name}_{template_name}"
        else:
            filename = f"emu{emulator_id}_{template_name}"

        filepath = os.path.join(debug_folder, filename)

        # Сохранить
        cv2.imwrite(filepath, debug_img)
        logger.debug(f"Debug скриншот: {filepath}")

    except Exception as e:
        logger.error(f"Ошибка сохранения debug скриншота: {e}")


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


def set_debug_mode(enabled):
    """
    Включает/выключает debug режим

    Args:
        enabled: True для включения, False для выключения
    """
    global DEBUG_MODE
    DEBUG_MODE = enabled
    logger.info(f"Debug режим распознавания: {'ВКЛ' if enabled else 'ВЫКЛ'}")