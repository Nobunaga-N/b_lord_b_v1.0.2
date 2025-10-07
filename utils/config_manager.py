"""
Работа с конфигурационными файлами
"""

import os
import yaml


def load_config(config_path, silent=False):
    """
    Загружает конфиг из YAML файла

    Args:
        config_path: Путь к YAML файлу
        silent: Если True, не выводить логи (по умолчанию False)

    Returns:
        dict: Данные из конфига или пустой dict если файл не существует
    """

    # Создать папку configs если не существует
    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    if not os.path.exists(config_path):
        if not silent:
            print(f"[WARNING] Файл конфига не найден: {config_path}")
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if data is None:
            return {}

        if not silent:
            print(f"[INFO] Конфиг загружен: {config_path}")
        return data

    except Exception as e:
        if not silent:
            print(f"[ERROR] Ошибка при загрузке конфига {config_path}: {e}")
        return {}


def save_config(config_path, config_data, silent=False):
    """
    Сохраняет конфиг в YAML файл

    Args:
        config_path: Путь к YAML файлу
        config_data: Данные для сохранения (dict)
        silent: Если True, не выводить логи (по умолчанию False)
    """

    try:
        # Создать папку если не существует
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

        if not silent:
            print(f"[INFO] Конфиг сохранён: {config_path}")

    except Exception as e:
        if not silent:
            print(f"[ERROR] Ошибка при сохранении конфига {config_path}: {e}")