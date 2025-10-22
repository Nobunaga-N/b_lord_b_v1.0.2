"""
База данных для хранения состояния зданий и строителей
Управление прокачкой зданий через SQLite

ОБНОВЛЕНО: Полная поддержка первичного сканирования + постройка зданий

Версия: 2.0
Дата обновления: 2025-01-21
Изменения:
- Добавлено поле action (upgrade/build) в таблицу buildings
- Реализовано первичное сканирование
- Автоматическое сканирование при level=0
- Правильная обработка зданий которые нужно построить
"""

import os
import sqlite3
import yaml
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from utils.logger import logger
from utils.image_recognition import find_image, get_screenshot
import re

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BuildingDatabase:
    """
    Класс для работы с базой данных зданий

    Управляет:
    - Уровнями зданий для каждого эмулятора
    - Статусом строителей (свободен/занят)
    - Заморозкой эмуляторов при нехватке ресурсов
    - Логикой выбора следующего здания для прокачки
    - Первичным сканированием уровней
    """

    # Путь к базе данных
    DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'bot.db')

    # Путь к конфигу порядка прокачки
    CONFIG_PATH = os.path.join(BASE_DIR, 'configs', 'building_order.yaml')

    # Область поиска иконок строителей (x1, y1, x2, y2)
    BUILDERS_SEARCH_AREA = (10, 115, 145, 179)

    # Шаблоны иконок строителей
    BUILDER_TEMPLATES = {
        (0, 3): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_0_3.png'),
        (1, 3): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_1_3.png'),
        (2, 3): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_2_3.png'),
        (3, 3): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_3_3.png'),
        (0, 4): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_0_4.png'),
        (1, 4): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_1_4.png'),
        (2, 4): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_2_4.png'),
        (3, 4): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_3_4.png'),
        (4, 4): os.path.join(BASE_DIR, 'data', 'templates', 'building', 'builders_4_4.png'),
    }

    def __init__(self):
        """Инициализация подключения к БД и загрузка конфигурации"""
        # Создаём директорию для БД если её нет
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        # Подключаемся к БД
        self.conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Создаём таблицы если их нет
        self._create_tables()

        # Загружаем конфигурацию порядка прокачки
        self._load_building_config()

        # Инициализируем OCR для определения строителей
        try:
            from utils.ocr_engine import OCREngine
            self._ocr_engine = OCREngine()
        except Exception as e:
            logger.warning(f"⚠️ Не удалось инициализировать OCR для строителей: {e}")
            self._ocr_engine = None

        logger.info("✅ BuildingDatabase инициализирована")

    def _create_tables(self):
        """Создать таблицы если их нет"""
        cursor = self.conn.cursor()

        # Таблица зданий (ОБНОВЛЕНА: добавлено поле action)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emulator_id INTEGER NOT NULL,
                building_name TEXT NOT NULL,
                building_type TEXT NOT NULL,
                building_index INTEGER,
                current_level INTEGER NOT NULL DEFAULT 0,
                upgrading_to_level INTEGER,
                target_level INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'idle',
                action TEXT NOT NULL DEFAULT 'upgrade',
                timer_finish TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(emulator_id, building_name, building_index)
            )
        """)

        # Таблица строителей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS builders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emulator_id INTEGER NOT NULL,
                builder_slot INTEGER NOT NULL,
                is_busy BOOLEAN NOT NULL DEFAULT 0,
                building_id INTEGER,
                finish_time TIMESTAMP,
                FOREIGN KEY (building_id) REFERENCES buildings(id),
                UNIQUE(emulator_id, builder_slot)
            )
        """)

        # Таблица заморозки эмуляторов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emulator_freeze (
                emulator_id INTEGER PRIMARY KEY,
                freeze_until TIMESTAMP NOT NULL,
                reason TEXT
            )
        """)

        self.conn.commit()
        logger.debug("✅ Таблицы БД проверены/созданы")

    def _load_building_config(self):
        """Загрузить конфигурацию порядка прокачки из YAML"""
        try:
            with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
                self.building_config = yaml.safe_load(f)
            logger.debug(f"✅ Конфиг загружен: {self.CONFIG_PATH}")
        except FileNotFoundError:
            logger.error(f"❌ Файл не найден: {self.CONFIG_PATH}")
            self.building_config = {}
        except yaml.YAMLError as e:
            logger.error(f"❌ Ошибка парсинга YAML: {e}")
            self.building_config = {}

    def close(self):
        """Закрыть соединение с БД"""
        if self.conn:
            self.conn.close()
            logger.debug("✅ Соединение с БД закрыто")

    # ===== ПЕРВИЧНОЕ СКАНИРОВАНИЕ =====

    def _extract_unique_buildings(self) -> List[Dict[str, Any]]:
        """
        Извлечь уникальный список зданий из building_order.yaml

        ИСПРАВЛЕНО: Правильно определяет action для каждого экземпляра множественного здания

        Логика:
        - Проходим по уровням лорда ПО ПОРЯДКУ (10→18)
        - Отслеживаем для каждого здания сколько экземпляров УЖЕ ПОСТРОЕНО
        - action='upgrade' с count=N означает что N экземпляров построены
        - action='build' означает что строится НОВЫЙ экземпляр

        Returns:
            list: список записей для БД с полями:
                  {name: str, index: int|None, max_target_level: int, type: str, action: str}
        """
        logger.debug("📋 Извлечение уникального списка зданий из конфига...")

        # Словарь для отслеживания зданий
        # key: name, value: {built_count: int, total_count: int, max_target: int, type: str}
        buildings_tracking = {}

        # Проверяем что конфиг загружен
        if not self.building_config:
            logger.error("❌ building_config пуст!")
            return []

        # Проходим по уровням лорда ПО ПОРЯДКУ
        for level in range(10, 19):
            lord_key = f"lord_{level}"

            if lord_key not in self.building_config:
                continue

            config = self.building_config[lord_key]

            # Проверяем наличие ключа 'buildings'
            if 'buildings' not in config or not isinstance(config['buildings'], list):
                continue

            buildings_list = config['buildings']

            for building in buildings_list:
                # Проверяем обязательные поля
                if 'name' not in building:
                    continue

                name = building['name']
                count = building.get('count', 1)
                target = building.get('target_level', 1)
                btype = building.get('type', 'unique')
                action = building.get('action', 'upgrade')

                # Инициализируем отслеживание для этого здания
                if name not in buildings_tracking:
                    buildings_tracking[name] = {
                        'built_count': 0,  # Сколько экземпляров уже построено
                        'total_count': 0,  # Сколько экземпляров будет всего
                        'max_target_level': 0,
                        'type': btype,
                        'has_build_action': False  # Встречалось ли action='build'
                    }

                # Обновляем информацию о здании
                if action == 'upgrade':
                    # Эти экземпляры УЖЕ ПОСТРОЕНЫ
                    if count > buildings_tracking[name]['built_count']:
                        buildings_tracking[name]['built_count'] = count

                elif action == 'build':
                    # Строятся НОВЫЕ экземпляры
                    if count > buildings_tracking[name]['total_count']:
                        buildings_tracking[name]['total_count'] = count
                    # Отмечаем что встретили action='build'
                    buildings_tracking[name]['has_build_action'] = True

                # Обновляем максимальный target_level
                if target > buildings_tracking[name]['max_target_level']:
                    buildings_tracking[name]['max_target_level'] = target

                # Обновляем общее количество (на случай если total не обновился из build)
                if count > buildings_tracking[name]['total_count']:
                    buildings_tracking[name]['total_count'] = count

        # Формируем результат
        result = []

        for name, data in buildings_tracking.items():
            built_count = data['built_count']  # Сколько уже построено
            total_count = data['total_count']  # Сколько будет всего
            max_target = data['max_target_level']
            btype = data['type']
            has_build_action = data['has_build_action']  # Встречалось ли action='build'

            if total_count > 1:
                # Множественное здание - создаем запись для каждого экземпляра
                for index in range(1, total_count + 1):
                    # КЛЮЧЕВАЯ ЛОГИКА:
                    # Если индекс <= built_count → здание УЖЕ ПОСТРОЕНО (action='upgrade')
                    # Если индекс > built_count → здание НУЖНО ПОСТРОИТЬ (action='build')
                    instance_action = 'upgrade' if index <= built_count else 'build'

                    result.append({
                        'name': name,
                        'index': index,
                        'max_target_level': max_target,
                        'type': btype,
                        'action': instance_action
                    })
            else:
                # Уникальное здание
                # ✅ ИСПРАВЛЕНО: Если встречалось action='build' → нужно строить
                unique_action = 'build' if has_build_action else 'upgrade'

                result.append({
                    'name': name,
                    'index': None,
                    'max_target_level': max_target,
                    'type': btype,
                    'action': unique_action
                })

        logger.info(f"✅ Найдено {len(result)} записей зданий")

        # Дебаг: выводим первые 5 записей
        for i, b in enumerate(result[:5], 1):
            index_str = f"#{b['index']}" if b['index'] else ""
            logger.debug(f"  {i}. {b['name']}{index_str} (max_level={b['max_target_level']}, action={b['action']})")

        return result

    def initialize_buildings_for_emulator(self, emulator_id: int, total_builders: int = 3) -> bool:
        """
        Инициализировать записи для всех зданий эмулятора в БД

        ИСПРАВЛЕНО: Теперь работает с новым форматом _extract_unique_buildings(),
        где каждый экземпляр множественного здания имеет свой action

        Args:
            emulator_id: ID эмулятора
            total_builders: общее количество строителей (3 или 4)

        Returns:
            bool: True если успешно
        """
        logger.info(f"🏗️ Инициализация зданий для эмулятора {emulator_id}...")

        cursor = self.conn.cursor()

        # Проверяем, не инициализирован ли уже этот эмулятор
        cursor.execute("""
            SELECT COUNT(*) FROM buildings WHERE emulator_id = ?
        """, (emulator_id,))

        count = cursor.fetchone()[0]

        if count > 0:
            logger.warning(f"⚠️ Эмулятор {emulator_id} уже инициализирован ({count} зданий)")
            return True

        # Получаем список зданий из конфига
        buildings_list = self._extract_unique_buildings()

        # Создаем записи для каждого здания
        buildings_created = 0

        for building_data in buildings_list:
            name = building_data['name']
            index = building_data.get('index')  # None для уникальных, номер для множественных
            max_target = building_data['max_target_level']
            btype = building_data['type']
            action = building_data['action']

            # Создаем запись в БД
            if index is not None:
                # Множественное здание с индексом
                cursor.execute("""
                    INSERT INTO buildings 
                    (emulator_id, building_name, building_type, building_index, 
                     current_level, target_level, status, action)
                    VALUES (?, ?, ?, ?, 0, ?, 'idle', ?)
                """, (emulator_id, name, btype, index, max_target, action))
            else:
                # Уникальное здание
                cursor.execute("""
                    INSERT INTO buildings 
                    (emulator_id, building_name, building_type, building_index, 
                     current_level, target_level, status, action)
                    VALUES (?, ?, ?, NULL, 0, ?, 'idle', ?)
                """, (emulator_id, name, btype, max_target, action))

            buildings_created += 1

        # Инициализируем строителей
        for slot in range(1, total_builders + 1):
            cursor.execute("""
                INSERT INTO builders 
                (emulator_id, builder_slot, is_busy)
                VALUES (?, ?, 0)
            """, (emulator_id, slot))

        self.conn.commit()

        logger.success(f"✅ Создано {buildings_created} записей зданий и {total_builders} строителей")
        return True

    def scan_building_level(self, emulator: dict, building_name: str,
                           building_index: Optional[int] = None) -> bool:
        """
        Просканировать уровень ОДНОГО здания и обновить в БД

        ВАЖНО: Не сканирует здания с action='build' и level=0
        (они еще не построены в игре)

        Args:
            emulator: объект эмулятора
            building_name: название здания
            building_index: индекс для множественных зданий

        Returns:
            bool: True если успешно
        """
        emulator_id = emulator.get('id', 0)
        emulator_name = emulator.get('name', f'Emulator-{emulator_id}')

        # Получаем информацию о здании из БД
        building = self.get_building(emulator_id, building_name, building_index)

        if not building:
            logger.error(f"[{emulator_name}] ❌ Здание не найдено в БД: {building_name}")
            return False

        # КРИТИЧЕСКАЯ ПРОВЕРКА: если action='build' и level=0 - здание не построено
        if building['action'] == 'build' and building['current_level'] == 0:
            logger.warning(f"[{emulator_name}] ⏭️ {building_name}: здание не построено (action=build, level=0)")
            return False

        logger.info(f"[{emulator_name}] 🔍 Сканирование: {building_name}" +
                    (f" #{building_index}" if building_index else ""))

        # Импортируем NavigationPanel
        from functions.building.navigation_panel import NavigationPanel
        nav_panel = NavigationPanel()

        # Получаем уровень через NavigationPanel
        level = nav_panel.get_building_level(emulator, building_name, building_index)

        if level is None:
            logger.error(f"[{emulator_name}] ❌ Не удалось получить уровень здания")
            return False

        # Обновляем уровень в БД
        cursor = self.conn.cursor()

        if building_index is not None:
            cursor.execute("""
                UPDATE buildings 
                SET current_level = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_name = ? AND building_index = ?
            """, (level, emulator_id, building_name, building_index))
        else:
            cursor.execute("""
                UPDATE buildings 
                SET current_level = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_name = ? AND building_index IS NULL
            """, (level, emulator_id, building_name))

        self.conn.commit()

        logger.success(f"[{emulator_name}] ✅ Обновлено в БД: {building_name}" +
                       (f" #{building_index}" if building_index else "") +
                       f" → Lv.{level}")

        return True

    def perform_initial_scan(self, emulator: dict) -> bool:
        """
        Выполнить первичное сканирование ВСЕХ зданий с level=0

        ИСПРАВЛЕНО:
        - Обработка результатов сразу после сканирования каждого раздела
        - Правильная навигация к разделу "Развитие"
        - Корректное сопоставление множественных зданий

        Args:
            emulator: объект эмулятора

        Returns:
            bool: True если успешно
        """
        emulator_id = emulator.get('id', 0)
        emulator_name = emulator.get('name', f'Emulator-{emulator_id}')

        logger.info(f"[{emulator_name}] 🔍 НАЧАЛО ПЕРВИЧНОГО СКАНИРОВАНИЯ")

        # 1. Получить все здания для сканирования
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT building_name, building_index, action
            FROM buildings 
            WHERE emulator_id = ? AND current_level = 0
            ORDER BY building_name, building_index
        """, (emulator_id,))

        buildings_to_scan = cursor.fetchall()

        if not buildings_to_scan:
            logger.info(f"[{emulator_name}] ✅ Все здания уже просканированы")
            return True

        # 2. Фильтруем: оставляем только action='upgrade'
        scannable = []
        skipped_build = []

        for row in buildings_to_scan:
            building_name = row[0]
            building_index = row[1]
            action = row[2]

            if action == 'build':
                skipped_build.append((building_name, building_index))
            else:
                scannable.append((building_name, building_index))

        total = len(scannable)
        logger.info(f"[{emulator_name}] 📋 Найдено зданий для сканирования: {total}")

        if skipped_build:
            logger.info(f"[{emulator_name}] ⏭️ Пропущено непостроенных зданий: {len(skipped_build)}")

        if total == 0:
            logger.info(f"[{emulator_name}] ✅ Нет зданий для сканирования")
            return True

        # 3. Сгруппировать здания по разделам
        groups = self._group_buildings_by_section(scannable)

        logger.info(f"[{emulator_name}] 📂 Разделов для сканирования: {len(groups)}")

        # 4. Импортируем NavigationPanel
        from functions.building.navigation_panel import NavigationPanel
        nav_panel = NavigationPanel()

        # Счетчики для финальной статистики
        total_success_count = 0
        total_failed_count = 0

        # 5. Сканируем каждый раздел и СРАЗУ обновляем БД
        section_num = 0
        for section_key, buildings_in_section in groups.items():
            section_num += 1
            logger.info(f"[{emulator_name}] 📂 [{section_num}/{len(groups)}] Раздел: {section_key}")
            logger.debug(f"[{emulator_name}]    Зданий в разделе: {len(buildings_in_section)}")

            # Открыть панель навигации
            if not nav_panel.open_navigation_panel(emulator):
                logger.error(f"[{emulator_name}] ❌ Не удалось открыть панель навигации")
                total_failed_count += len(buildings_in_section)
                continue

            # Получить конфигурацию первого здания для навигации
            first_building_name = buildings_in_section[0][0]
            building_config = nav_panel.get_building_config(first_building_name)

            if not building_config:
                logger.error(f"[{emulator_name}] ❌ Конфиг не найден для {first_building_name}")
                total_failed_count += len(buildings_in_section)
                continue

            # Перейти к разделу
            if not self._navigate_to_section(emulator, nav_panel, building_config):
                logger.error(f"[{emulator_name}] ❌ Не удалось перейти к разделу")
                total_failed_count += len(buildings_in_section)
                continue

            # Небольшая пауза после навигации
            time.sleep(0.5)

            # Парсить все здания на экране
            from utils.image_recognition import get_screenshot
            screenshot = get_screenshot(emulator)
            if screenshot is None:
                logger.error(f"[{emulator_name}] ❌ Не удалось получить скриншот")
                total_failed_count += len(buildings_in_section)
                continue

            all_buildings_on_screen = nav_panel.ocr.parse_navigation_panel(
                screenshot,
                emulator_id=emulator_id
            )

            if not all_buildings_on_screen:
                logger.warning(f"[{emulator_name}] ⚠️ Не удалось распознать здания в разделе {section_key}")
                total_failed_count += len(buildings_in_section)
                continue

            logger.info(f"[{emulator_name}]    Распознано зданий на экране: {len(all_buildings_on_screen)}")

            # Логируем все распознанные здания для отладки
            for b in all_buildings_on_screen:
                logger.debug(f"[{emulator_name}]      📍 {b['name']} Lv.{b['level']} (Y: {b['y']})")

            # Создаем словарь для группировки найденных зданий по названию
            found_by_name = {}

            for building in all_buildings_on_screen:
                building_name = building['name']

                # Проверяем, относится ли это здание к текущему разделу
                is_relevant = False
                for target_name, target_index in buildings_in_section:
                    # Нормализуем названия для сравнения
                    target_normalized = target_name.lower().replace(' ', '').replace('ё', 'е')
                    building_normalized = building_name.lower().replace(' ', '').replace('ё', 'е')

                    # Проверяем совпадение
                    if target_normalized in building_normalized or building_normalized in target_normalized:
                        is_relevant = True
                        # Используем целевое имя из БД (не из OCR)
                        building_name = target_name
                        break

                if not is_relevant:
                    continue

                # Добавляем здание в группу (если еще не добавлено)
                if building_name not in found_by_name:
                    found_by_name[building_name] = []

                # Проверяем, нет ли уже здания с такими же Y координатами (дубликат)
                is_duplicate = False
                for existing in found_by_name[building_name]:
                    if abs(existing['y'] - building['y']) < 5:  # Допуск 5 пикселей
                        is_duplicate = True
                        break

                if not is_duplicate:
                    found_by_name[building_name].append({
                        'level': building['level'],
                        'y': building['y'],
                        'name': building['name']
                    })

            # ОБНОВЛЯЕМ БД для зданий текущего раздела
            for building_name, building_index in buildings_in_section:
                if building_name not in found_by_name:
                    logger.warning(f"[{emulator_name}]      ✗ {building_name}: не найдено на экране")
                    total_failed_count += 1
                    continue

                found_instances = found_by_name[building_name]

                if building_index is not None:
                    # Множественное здание - сортируем по Y (сверху вниз)
                    found_instances_sorted = sorted(found_instances, key=lambda x: x['y'])

                    # Дебаг логирование для множественных зданий
                    logger.debug(f"[{emulator_name}] Обработка {building_name} (множественное):")
                    logger.debug(f"[{emulator_name}]   Найдено уникальных экземпляров: {len(found_instances_sorted)}")
                    for idx, inst in enumerate(found_instances_sorted):
                        logger.debug(f"[{emulator_name}]     [{idx + 1}] Lv.{inst['level']} (Y: {inst['y']})")

                    # Индекс в БД начинается с 1, в массиве с 0
                    idx = building_index - 1

                    if idx < len(found_instances_sorted):
                        level = found_instances_sorted[idx]['level']

                        # Обновляем в БД
                        cursor.execute("""
                                        UPDATE buildings 
                                        SET current_level = ?,
                                            last_updated = CURRENT_TIMESTAMP
                                        WHERE emulator_id = ? 
                                        AND building_name = ? 
                                        AND building_index = ?
                                    """, (level, emulator_id, building_name, building_index))

                        self.conn.commit()

                        logger.success(f"[{emulator_name}] ✅ {building_name} #{building_index} → Lv.{level}")
                        total_success_count += 1
                    else:
                        logger.error(f"[{emulator_name}] ❌ {building_name} #{building_index}: " +
                                     f"индекс {building_index} вне диапазона (найдено {len(found_instances_sorted)} уникальных)")
                        total_failed_count += 1

                else:
                    # Уникальное здание - берем первое найденное
                    if len(found_instances) > 0:
                        level = found_instances[0]['level']

                        cursor.execute("""
                                        UPDATE buildings 
                                        SET current_level = ?,
                                            last_updated = CURRENT_TIMESTAMP
                                        WHERE emulator_id = ? 
                                        AND building_name = ? 
                                        AND building_index IS NULL
                                    """, (level, emulator_id, building_name))

                        self.conn.commit()

                        logger.success(f"[{emulator_name}] ✅ {building_name} → Lv.{level}")
                        total_success_count += 1
                    else:
                        logger.error(f"[{emulator_name}] ❌ {building_name}: массив пуст")
                        total_failed_count += 1

            # Свернуть раздел после обработки
            nav_panel.reset_navigation_state(emulator)
            time.sleep(0.5)

        # 6. Итоги
        logger.info(f"[{emulator_name}] 📊 ИТОГО СКАНИРОВАНИЯ:")
        logger.info(f"[{emulator_name}]   ✅ Успешно: {total_success_count}")
        logger.info(f"[{emulator_name}]   ❌ Ошибки: {total_failed_count}")
        logger.info(f"[{emulator_name}]   ⏭️ Пропущено (не построено): {len(skipped_build)}")

        if total_failed_count > 0:
            logger.warning(f"[{emulator_name}] ⚠️ Сканирование завершено с ошибками")
            # Возвращаем True если хотя бы часть зданий просканирована
            return total_success_count > 0

        logger.success(f"[{emulator_name}] ✅ ПЕРВИЧНОЕ СКАНИРОВАНИЕ ЗАВЕРШЕНО УСПЕШНО")
        return True

    def _group_buildings_by_section(self, buildings: List[Tuple[str, Optional[int]]]) -> Dict[
        str, List[Tuple[str, Optional[int]]]]:
        """
        Сгруппировать здания по разделам навигации

        ИСПРАВЛЕНО: Дополнительная группировка по требованию скролла внутри раздела
        Это гарантирует что здания видимые сразу будут просканированы ПЕРЕД зданиями требующими скролл

        Args:
            buildings: список (building_name, building_index)

        Returns:
            dict: {section_key: [(building_name, building_index), ...]}
        """
        from functions.building.navigation_panel import NavigationPanel
        nav_panel = NavigationPanel()

        groups = {}

        for building_name, building_index in buildings:
            building_config = nav_panel.get_building_config(building_name)

            if not building_config:
                logger.warning(f"⚠️ Конфиг не найден для {building_name}, пропускаем")
                continue

            # Определяем ключ раздела
            if building_config.get('from_tasks_tab'):
                section_key = "Список дел"
            else:
                section = building_config.get('section', 'Unknown')
                subsection = building_config.get('subsection')

                # ИСПРАВЛЕНИЕ: Проверяем требуется ли скролл внутри раздела/подвкладки
                if subsection:
                    # Для подвкладок проверяем scroll_in_subsection
                    scroll_config = building_config.get('scroll_in_subsection', [])
                else:
                    # Для обычных разделов проверяем scroll_in_section
                    scroll_config = building_config.get('scroll_in_section', [])

                requires_scroll = len(scroll_config) > 0

                # Формируем ключ с учетом скролла
                if subsection:
                    base_key = f"{section} > {subsection}"
                else:
                    base_key = section

                # Добавляем маркер скролла к ключу
                if requires_scroll:
                    section_key = f"{base_key} (со скроллом)"
                else:
                    section_key = f"{base_key} (без скролла)"

            # Добавляем в группу
            if section_key not in groups:
                groups[section_key] = []

            groups[section_key].append((building_name, building_index))

        return groups

    def _navigate_to_section(self, emulator: dict, nav_panel, building_config: dict) -> bool:
        """
        Перейти к разделу используя конфигурацию здания

        ИСПРАВЛЕНО: Добавлена правильная навигация для всех типов разделов

        Args:
            emulator: объект эмулятора
            nav_panel: объект NavigationPanel
            building_config: конфигурация здания

        Returns:
            bool: True если успешно
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        # Если здание в "Список дел"
        if building_config.get('from_tasks_tab'):
            nav_panel.switch_to_tasks_tab(emulator)
            time.sleep(0.5)
            return True

        # Для зданий в "Список зданий"
        nav_panel.switch_to_buildings_tab(emulator)
        time.sleep(0.5)

        # Сбрасываем состояние навигации (сворачиваем все разделы)
        nav_panel.reset_navigation_state(emulator)

        # Открываем основной раздел
        section_name = building_config.get('section')
        if not nav_panel._open_section_by_name(emulator, section_name):
            logger.error(f"[{emulator_name}] ❌ Не удалось открыть раздел: {section_name}")
            return False

        time.sleep(0.5)

        # Если есть подвкладка
        if 'subsection' in building_config:
            subsection_name = building_config['subsection']
            subsection_data = building_config.get('subsection_data', {})

            # Свайпы для доступа к подвкладке (если нужно)
            if subsection_data.get('requires_scroll'):
                scroll_swipes = subsection_data.get('scroll_to_subsection', [])
                nav_panel.execute_swipes(emulator, scroll_swipes)
                time.sleep(0.3)

            # Открываем подвкладку
            if not nav_panel._open_section_by_name(emulator, subsection_name):
                logger.error(f"[{emulator_name}] ❌ Не удалось открыть подвкладку: {subsection_name}")
                return False

            time.sleep(0.5)

            # Свайпы внутри подвкладки для доступа к зданиям
            scroll_swipes = building_config.get('scroll_in_subsection', [])
            if scroll_swipes:
                nav_panel.execute_swipes(emulator, scroll_swipes)
                time.sleep(0.3)
        else:
            # Свайпы внутри основного раздела (если нужно)
            scroll_swipes = building_config.get('scroll_in_section', [])
            if scroll_swipes:
                nav_panel.execute_swipes(emulator, scroll_swipes)
                time.sleep(0.3)

        return True

    def has_unscanned_buildings(self, emulator_id: int) -> bool:
        """
        Проверить есть ли у эмулятора здания с неизвестным уровнем (level=0)
        которые нужно просканировать (исключая непостроенные)

        Args:
            emulator_id: ID эмулятора

        Returns:
            bool: True если есть непросканированные здания
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM buildings 
            WHERE emulator_id = ? AND current_level = 0 AND action != 'build'
        """, (emulator_id,))

        count = cursor.fetchone()[0]

        return count > 0

    def get_unscanned_buildings_count(self, emulator_id: int) -> int:
        """
        Получить количество непросканированных зданий (исключая непостроенные)

        Args:
            emulator_id: ID эмулятора

        Returns:
            int: количество зданий с level=0 которые нужно сканировать
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM buildings 
            WHERE emulator_id = ? AND current_level = 0 AND action != 'build'
        """, (emulator_id,))

        return cursor.fetchone()[0]

    # ===== ОПРЕДЕЛЕНИЕ КОЛИЧЕСТВА СТРОИТЕЛЕЙ =====

    def detect_builders_count(self, emulator: dict) -> Tuple[int, int]:
        """
        Определить количество строителей через OCR

        Область поиска: (10, 115, 145, 179)
        Ожидаемый формат текста: "0/3", "1/3", "2/4" и т.д.

        Args:
            emulator: Объект эмулятора с полями {id, name, port}

        Returns:
            (busy_count, total_count) - например (1, 3) означает 1 занят из 3 всего
        """
        emulator_id = emulator.get('id', 0)
        emulator_name = emulator.get('name', f'Emulator-{emulator_id}')

        # Получаем скриншот
        screenshot = get_screenshot(emulator)
        if screenshot is None:
            logger.error(f"❌ Не удалось получить скриншот эмулятора {emulator_name}")
            return (0, 3)

        # Область поиска слотов строительства
        x1, y1, x2, y2 = self.BUILDERS_SEARCH_AREA

        # Создаем OCR движок (если еще не создан)
        if not hasattr(self, '_ocr_engine'):
            from utils.ocr_engine import OCREngine
            self._ocr_engine = OCREngine(lang='en')
            logger.debug("✅ OCR движок инициализирован для парсинга строителей")

        # Распознаем текст в области
        elements = self._ocr_engine.recognize_text(
            screenshot,
            region=(x1, y1, x2, y2),
            min_confidence=0.5
        )

        # Ищем паттерн "X/Y"
        builder_pattern = re.compile(r'(\d+)\s*/\s*(\d+)')

        for element in elements:
            text = element['text'].strip()
            match = builder_pattern.search(text)

            if match:
                busy = int(match.group(1))
                total = int(match.group(2))

                # Валидация (в игре может быть только 3 или 4 строителя)
                if total in [3, 4] and 0 <= busy <= total:
                    logger.info(f"🔨 Строители: {busy}/{total} (распознано через OCR)")
                    return (busy, total)
                else:
                    logger.warning(f"⚠️ Некорректные значения: {busy}/{total}, игнорируем")

        # Если ничего не распознано - пробуем с более низким порогом
        logger.debug("🔍 Первая попытка не удалась, пробуем с min_confidence=0.3")

        elements = self._ocr_engine.recognize_text(
            screenshot,
            region=(x1, y1, x2, y2),
            min_confidence=0.3
        )

        for element in elements:
            text = element['text'].strip()
            match = builder_pattern.search(text)

            if match:
                busy = int(match.group(1))
                total = int(match.group(2))

                if total in [3, 4] and 0 <= busy <= total:
                    logger.info(f"🔨 Строители: {busy}/{total} (распознано с низкой уверенностью)")
                    return (busy, total)

        # Если ничего не распознано - логируем для отладки
        logger.warning(f"⚠️ Не удалось распознать слоты строителей")
        logger.debug(f"📊 Распознанные элементы: {[e['text'] for e in elements]}")

        # Значение по умолчанию (безопасное предположение)
        logger.info("ℹ️ Используем значение по умолчанию: 0/3")
        return (0, 3)

    def initialize_builders(self, emulator_id: int, slots: int = 3):
        """
        Инициализировать строителей для эмулятора

        Args:
            emulator_id: ID эмулятора
            slots: количество слотов строителей (3 или 4)
        """
        cursor = self.conn.cursor()

        logger.info(f"🔨 Инициализация {slots} строителей для эмулятора {emulator_id}...")

        for slot in range(1, slots + 1):
            cursor.execute("""
                INSERT OR IGNORE INTO builders 
                (emulator_id, builder_slot, is_busy)
                VALUES (?, ?, 0)
            """, (emulator_id, slot))

        self.conn.commit()
        logger.success(f"✅ Инициализировано {slots} строителей")

    def _find_building_in_config(self, building_name: str) -> Optional[Dict]:
        """
        Найти здание в конфиге и вернуть его параметры

        Ищет первое вхождение здания в конфиге для определения типа
        """
        for lord_level, config in self.building_config.items():
            for building in config['buildings']:
                if building['name'] == building_name:
                    return building
        return None

    # ===== РАБОТА С ЗДАНИЯМИ =====

    def get_building(self, emulator_id: int, building_name: str,
                     building_index: Optional[int] = None) -> Optional[Dict]:
        """
        Получить информацию о здании

        Returns:
            dict с полями: id, name, type, index, current_level, upgrading_to_level,
                          target_level, status, action, timer_finish
        """
        cursor = self.conn.cursor()

        if building_index is not None:
            cursor.execute("""
                SELECT * FROM buildings 
                WHERE emulator_id = ? AND building_name = ? AND building_index = ?
            """, (emulator_id, building_name, building_index))
        else:
            cursor.execute("""
                SELECT * FROM buildings 
                WHERE emulator_id = ? AND building_name = ? AND building_index IS NULL
            """, (emulator_id, building_name))

        row = cursor.fetchone()

        if row:
            return {
                'id': row['id'],
                'name': row['building_name'],
                'type': row['building_type'],
                'index': row['building_index'],
                'current_level': row['current_level'],
                'upgrading_to_level': row['upgrading_to_level'],
                'target_level': row['target_level'],
                'status': row['status'],
                'action': row['action'],
                'timer_finish': row['timer_finish']
            }

        return None

    def update_building_level(self, emulator_id: int, building_name: str,
                             building_index: Optional[int], new_level: int):
        """
        Обновить уровень здания

        Args:
            emulator_id: ID эмулятора
            building_name: название здания
            building_index: индекс (для множественных)
            new_level: новый уровень
        """
        cursor = self.conn.cursor()

        if building_index is not None:
            cursor.execute("""
                UPDATE buildings 
                SET current_level = ?, 
                    upgrading_to_level = NULL,
                    status = 'idle',
                    timer_finish = NULL,
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_name = ? AND building_index = ?
            """, (new_level, emulator_id, building_name, building_index))
        else:
            cursor.execute("""
                UPDATE buildings 
                SET current_level = ?, 
                    upgrading_to_level = NULL,
                    status = 'idle',
                    timer_finish = NULL,
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_name = ? AND building_index IS NULL
            """, (new_level, emulator_id, building_name))

        self.conn.commit()
        logger.info(f"✅ Обновлён уровень: {building_name} → {new_level}")

    def set_building_upgrading(self, emulator_id: int, building_name: str,
                               building_index: Optional[int], timer_finish: datetime,
                               builder_slot: int):
        """
        Пометить здание как улучшающееся

        Args:
            emulator_id: ID эмулятора
            building_name: название здания
            building_index: индекс (для множественных)
            timer_finish: время завершения постройки
            builder_slot: номер занятого строителя
        """
        cursor = self.conn.cursor()

        # Получаем текущее здание
        building = self.get_building(emulator_id, building_name, building_index)

        if not building:
            logger.error(f"❌ Здание не найдено: {building_name}")
            return

        building_id = building['id']
        current_level = building['current_level']
        upgrading_to = current_level + 1

        # Обновляем статус здания
        if building_index is not None:
            cursor.execute("""
                UPDATE buildings 
                SET upgrading_to_level = ?,
                    status = 'upgrading',
                    timer_finish = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_name = ? AND building_index = ?
            """, (upgrading_to, timer_finish, emulator_id, building_name, building_index))
        else:
            cursor.execute("""
                UPDATE buildings 
                SET upgrading_to_level = ?,
                    status = 'upgrading',
                    timer_finish = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_name = ? AND building_index IS NULL
            """, (upgrading_to, timer_finish, emulator_id, building_name))

        # Занимаем строителя
        cursor.execute("""
            UPDATE builders 
            SET is_busy = 1,
                building_id = ?,
                finish_time = ?
            WHERE emulator_id = ? AND builder_slot = ?
        """, (building_id, timer_finish, emulator_id, builder_slot))

        self.conn.commit()

        logger.info(f"✅ Здание {building_name} начало улучшение → Lv.{upgrading_to}")
        logger.info(f"🔨 Строитель #{builder_slot} занят до {timer_finish}")

    def set_building_constructed(self, emulator_id: int, building_name: str,
                                 building_index: Optional[int], timer_finish: datetime,
                                 builder_slot: int):
        """
        Пометить здание как строящееся (постройка нового здания)

        ИСПРАВЛЕНО: Теперь обновляет action='build' → action='upgrade'
        после начала постройки

        После постройки здание будет иметь level=1

        Args:
            emulator_id: ID эмулятора
            building_name: название здания
            building_index: индекс (для множественных)
            timer_finish: время завершения постройки
            builder_slot: номер занятого строителя
        """
        cursor = self.conn.cursor()

        # Получаем текущее здание
        building = self.get_building(emulator_id, building_name, building_index)

        if not building:
            logger.error(f"❌ Здание не найдено: {building_name}")
            return

        building_id = building['id']

        # ✅ ИСПРАВЛЕНО: Обновляем статус И action
        # После начала постройки action меняется с 'build' на 'upgrade'
        if building_index is not None:
            cursor.execute("""
                UPDATE buildings 
                SET upgrading_to_level = 1,
                    status = 'upgrading',
                    timer_finish = ?,
                    action = 'upgrade',
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_name = ? AND building_index = ?
            """, (timer_finish, emulator_id, building_name, building_index))
        else:
            cursor.execute("""
                UPDATE buildings 
                SET upgrading_to_level = 1,
                    status = 'upgrading',
                    timer_finish = ?,
                    action = 'upgrade',
                    last_updated = CURRENT_TIMESTAMP
                WHERE emulator_id = ? AND building_name = ? AND building_index IS NULL
            """, (timer_finish, emulator_id, building_name))

        # Занимаем строителя
        cursor.execute("""
            UPDATE builders 
            SET is_busy = 1,
                building_id = ?,
                finish_time = ?
            WHERE emulator_id = ? AND builder_slot = ?
        """, (building_id, timer_finish, emulator_id, builder_slot))

        self.conn.commit()

        logger.info(f"✅ Здание {building_name} начало постройку → Lv.1 (action='build' → 'upgrade')")
        logger.info(f"🔨 Строитель #{builder_slot} занят до {timer_finish}")

    # ===== РАБОТА СО СТРОИТЕЛЯМИ =====

    def get_free_builder(self, emulator_id: int) -> Optional[int]:
        """
        Получить номер свободного строителя

        Returns:
            int: номер слота свободного строителя или None если все заняты
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT builder_slot FROM builders 
            WHERE emulator_id = ? AND is_busy = 0
            ORDER BY builder_slot
            LIMIT 1
        """, (emulator_id,))

        row = cursor.fetchone()

        return row[0] if row else None

    def free_builder(self, emulator_id: int, builder_slot: int):
        """
        Освободить строителя

        Args:
            emulator_id: ID эмулятора
            builder_slot: номер слота строителя
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            UPDATE builders 
            SET is_busy = 0,
                building_id = NULL,
                finish_time = NULL
            WHERE emulator_id = ? AND builder_slot = ?
        """, (emulator_id, builder_slot))

        self.conn.commit()

        logger.info(f"✅ Строитель #{builder_slot} освобожден")

    def get_busy_builders_count(self, emulator_id: int) -> int:
        """
        Получить количество занятых строителей

        Returns:
            int: количество занятых строителей
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM builders 
            WHERE emulator_id = ? AND is_busy = 1
        """, (emulator_id,))

        return cursor.fetchone()[0]

    # ===== ЛОГИКА ВЫБОРА СЛЕДУЮЩЕГО ЗДАНИЯ =====

    def _check_intermediate_buildings_ready(self, emulator_id: int, lord_level: int) -> bool:
        """
        Проверить готовы ли все промежуточные здания перед прокачкой Лорда

        Args:
            emulator_id: ID эмулятора
            lord_level: текущий уровень Лорда

        Returns:
            bool: True если все промежуточные здания готовы
        """
        config_key = f"lord_{lord_level}"
        config = self.building_config.get(config_key)

        if not config:
            return True

        # Проверяем все здания кроме Лорда
        for building_cfg in config['buildings']:
            name = building_cfg['name']

            if name == "Лорд":
                continue

            count = building_cfg['count']
            target = building_cfg['target_level']

            # Проверяем каждое здание
            if count > 1:
                for index in range(1, count + 1):
                    building = self.get_building(emulator_id, name, index)

                    if not building:
                        logger.debug(f"⏸️ Промежуточное здание не найдено: {name} #{index}")
                        return False

                    if building['current_level'] < target:
                        logger.debug(f"⏸️ Промежуточное здание не готово: {name} #{index} ({building['current_level']}/{target})")
                        return False
            else:
                building = self.get_building(emulator_id, name, None)

                if not building:
                    logger.debug(f"⏸️ Промежуточное здание не найдено: {name}")
                    return False

                if building['current_level'] < target:
                    logger.debug(f"⏸️ Промежуточное здание не готово: {name} ({building['current_level']}/{target})")
                    return False

        return True

    def _can_construct_building(self, emulator_id: int, building_name: str) -> bool:
        """
        Проверить можно ли построить здание

        Для постройки нужно чтобы уровень Лорда был достаточным

        Args:
            emulator_id: ID эмулятора
            building_name: название здания

        Returns:
            bool: True если можно построить
        """
        # Получаем уровень Лорда
        lord = self.get_building(emulator_id, "Лорд")

        if not lord:
            return False

        lord_level = lord['current_level']

        # Ищем в каком конфиге это здание появляется
        for config_key, config in self.building_config.items():
            # Извлекаем уровень из ключа (например "lord_13" → 13)
            required_lord_level = int(config_key.split('_')[1])

            for building_cfg in config['buildings']:
                if building_cfg['name'] == building_name and building_cfg.get('action') == 'build':
                    # Проверяем что уровень Лорда достаточный
                    if lord_level >= required_lord_level:
                        return True

        return False

    def get_next_building_to_upgrade(self, emulator: dict,
                                    auto_scan: bool = True) -> Optional[Dict]:
        """
        Определить следующее здание для прокачки

        С АВТОМАТИЧЕСКИМ СКАНИРОВАНИЕМ если level=0

        Args:
            emulator: объект эмулятора
            auto_scan: автоматически сканировать если level=0

        Returns:
            dict: информация о следующем здании или None
        """
        emulator_id = emulator.get('id', 0)
        emulator_name = emulator.get('name', f'Emulator-{emulator_id}')

        # 1. Получить текущий уровень Лорда
        lord = self.get_building(emulator_id, "Лорд")

        if not lord:
            logger.error(f"[{emulator_name}] ❌ Лорд не найден в БД")
            return None

        lord_level = lord['current_level']

        # КРИТИЧЕСКАЯ ПРОВЕРКА: если уровень Лорда = 0, сканируем его
        if lord_level == 0:
            if auto_scan:
                logger.warning(f"[{emulator_name}] ⚠️ Уровень Лорда неизвестен, сканируем...")
                success = self.scan_building_level(emulator, "Лорд", None)

                if not success:
                    logger.error(f"[{emulator_name}] ❌ Не удалось просканировать Лорда")
                    return None

                # Перезагружаем данные Лорда
                lord = self.get_building(emulator_id, "Лорд")
                lord_level = lord['current_level']
            else:
                logger.error(f"[{emulator_name}] ❌ Уровень Лорда неизвестен (level=0)")
                return None

        logger.debug(f"[{emulator_name}] Текущий уровень Лорда: {lord_level}")

        # 2. Загрузить конфиг для текущего уровня
        config_key = f"lord_{lord_level}"
        config = self.building_config.get(config_key)

        if not config:
            logger.error(f"[{emulator_name}] ❌ Нет конфига для {config_key}")
            return None

        # 3. Пройти по списку зданий ПО ПОРЯДКУ
        for building_cfg in config['buildings']:
            name = building_cfg['name']
            count = building_cfg['count']
            target = building_cfg['target_level']
            btype = building_cfg['type']
            action = building_cfg.get('action', 'upgrade')

            # 4. Если множественное здание (count > 1)
            if count > 1:
                # Найти здание с МИНИМАЛЬНЫМ уровнем из группы
                for index in range(1, count + 1):
                    building = self.get_building(emulator_id, name, index)

                    if not building:
                        # Здание не существует - нужно построить
                        if action == 'build':
                            # Проверяем условия постройки
                            if self._can_construct_building(emulator_id, name):
                                return {
                                    'name': name,
                                    'index': index,
                                    'current_level': 0,
                                    'target_level': target,
                                    'is_lord': False,
                                    'action': 'construct'
                                }
                        continue

                    # КРИТИЧЕСКАЯ ПРОВЕРКА: если level=0 и action='upgrade', сканируем
                    if building['current_level'] == 0 and action == 'upgrade':
                        if auto_scan:
                            logger.warning(f"[{emulator_name}] ⚠️ {name} #{index}: уровень неизвестен, сканируем...")
                            success = self.scan_building_level(emulator, name, index)

                            if not success:
                                logger.error(f"[{emulator_name}] ❌ Не удалось просканировать {name} #{index}")
                                continue

                            # Перезагружаем данные здания
                            building = self.get_building(emulator_id, name, index)
                        else:
                            logger.warning(f"[{emulator_name}] ⚠️ {name} #{index}: уровень неизвестен (level=0), пропускаем")
                            continue

                    # Если action='build' и level=0 - здание не построено, пропускаем
                    if action == 'build' and building['current_level'] == 0:
                        continue

                    # Проверка: нельзя улучшать выше уровня Лорда
                    if building['current_level'] + 1 > lord_level:
                        logger.debug(f"[{emulator_name}] ⏸️ {name} #{index}: уровень {building['current_level']+1} > Лорд {lord_level}")
                        continue

                    # Проверяем: не улучшается ли + не достигло target
                    if (building['status'] != 'upgrading' and
                        building['current_level'] < target):
                        return {
                            'name': name,
                            'index': index,
                            'current_level': building['current_level'],
                            'target_level': target,
                            'is_lord': (name == "Лорд"),
                            'action': action
                        }

            # 5. Если уникальное здание (count = 1)
            else:
                building = self.get_building(emulator_id, name, None)

                if not building:
                    # Здание не существует - нужно построить
                    if action == 'build':
                        if self._can_construct_building(emulator_id, name):
                            return {
                                'name': name,
                                'index': None,
                                'current_level': 0,
                                'target_level': target,
                                'is_lord': (name == "Лорд"),
                                'action': 'construct'
                            }
                    continue

                # КРИТИЧЕСКАЯ ПРОВЕРКА: если level=0 и action='upgrade', сканируем
                if building['current_level'] == 0 and action == 'upgrade':
                    if auto_scan:
                        logger.warning(f"[{emulator_name}] ⚠️ {name}: уровень неизвестен, сканируем...")
                        success = self.scan_building_level(emulator, name, None)

                        if not success:
                            logger.error(f"[{emulator_name}] ❌ Не удалось просканировать {name}")
                            continue

                        # Перезагружаем данные здания
                        building = self.get_building(emulator_id, name, None)
                    else:
                        logger.warning(f"[{emulator_name}] ⚠️ {name}: уровень неизвестен (level=0), пропускаем")
                        continue

                # Если action='build' и level=0 - здание не построено, пропускаем
                if action == 'build' and building['current_level'] == 0:
                    continue

                # Проверка для Лорда: нельзя улучшать пока не готовы промежуточные
                if name == "Лорд":
                    all_ready = self._check_intermediate_buildings_ready(emulator_id, lord_level)
                    if not all_ready:
                        logger.debug(f"[{emulator_name}] ⏸️ Лорд: промежуточные здания не готовы")
                        continue

                # Проверка: нельзя улучшать выше уровня Лорда (кроме самого Лорда)
                if name != "Лорд" and building['current_level'] + 1 > lord_level:
                    logger.debug(f"[{emulator_name}] ⏸️ {name}: уровень {building['current_level']+1} > Лорд {lord_level}")
                    continue

                # Проверяем: не улучшается ли + не достигло target
                if (building['status'] != 'upgrading' and
                    building['current_level'] < target):
                    return {
                        'name': name,
                        'index': None,
                        'current_level': building['current_level'],
                        'target_level': target,
                        'is_lord': (name == "Лорд"),
                        'action': action
                    }

        # Ничего не найдено
        logger.info(f"[{emulator_name}] ✅ Все здания для текущего уровня Лорда прокачаны")
        return None

    # ===== ЗАМОРОЗКА ЭМУЛЯТОРА =====

    def freeze_emulator(self, emulator_id: int, hours: int = 6, reason: str = "Нехватка ресурсов"):
        """
        Заморозить эмулятор на определенное время

        Args:
            emulator_id: ID эмулятора
            hours: количество часов заморозки
            reason: причина заморозки
        """
        cursor = self.conn.cursor()

        freeze_until = datetime.now() + timedelta(hours=hours)

        cursor.execute("""
            INSERT OR REPLACE INTO emulator_freeze 
            (emulator_id, freeze_until, reason)
            VALUES (?, ?, ?)
        """, (emulator_id, freeze_until, reason))

        self.conn.commit()

        logger.warning(f"❄️ Эмулятор {emulator_id} заморожен до {freeze_until} ({reason})")

    def is_emulator_frozen(self, emulator_id: int) -> bool:
        """
        Проверить заморожен ли эмулятор

        Returns:
            bool: True если эмулятор заморожен
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT freeze_until FROM emulator_freeze 
            WHERE emulator_id = ?
        """, (emulator_id,))

        row = cursor.fetchone()

        if not row:
            return False

        freeze_until = datetime.fromisoformat(row[0])

        if datetime.now() < freeze_until:
            return True
        else:
            # Заморозка истекла - удаляем запись
            cursor.execute("""
                DELETE FROM emulator_freeze WHERE emulator_id = ?
            """, (emulator_id,))
            self.conn.commit()
            return False

    def unfreeze_emulator(self, emulator_id: int):
        """
        Разморозить эмулятор принудительно

        Args:
            emulator_id: ID эмулятора
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            DELETE FROM emulator_freeze WHERE emulator_id = ?
        """, (emulator_id,))

        self.conn.commit()

        logger.info(f"✅ Эмулятор {emulator_id} разморожен")