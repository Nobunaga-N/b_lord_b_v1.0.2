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
import threading
from utils.function_freeze_manager import function_freeze_manager

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
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        # ✅ ДОБАВЛЕНО: Блокировка для thread-safety
        self.db_lock = threading.RLock()

        self.conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        self._create_tables()
        self._load_building_config()

        try:
            from utils.ocr_engine import OCREngine
            self._ocr_engine = OCREngine()
        except Exception as e:
            logger.warning(f"⚠️ Не удалось инициализировать OCR: {e}")
            self._ocr_engine = None

        logger.info("✅ BuildingDatabase инициализирована (Thread-Safe)")

    def _create_tables(self):
        """Создать таблицы если их нет"""
        with self.db_lock:
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

            # Таблица пофункциональной заморозки (НОВАЯ)
            # Позволяет замораживать функции НЕЗАВИСИМО друг от друга
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS function_freeze (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emulator_id INTEGER NOT NULL,
                    function_name TEXT NOT NULL,
                    freeze_until TIMESTAMP NOT NULL,
                    reason TEXT,
                    UNIQUE(emulator_id, function_name)
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

        ИСПРАВЛЕНО:
        - Правильно определяет action для каждого экземпляра множественного здания
        - Для множественных зданий отслеживает ПЕРСОНАЛЬНЫЙ target_level для КАЖДОГО экземпляра

        КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: После появления action='build' для здания,
        последующие action='upgrade' с большим count не увеличивают built_count,
        т.к. они означают прокачку ВКЛЮЧАЯ только что построенные здания.

        Логика:
        - Проходим по уровням лорда ПО ПОРЯДКУ (10→18)
        - Отслеживаем для каждого здания сколько экземпляров УЖЕ ПОСТРОЕНО
        - action='upgrade' с count=N означает что N экземпляров построены (только если не было action='build')
        - action='build' означает что строится НОВЫЙ экземпляр
        - Для множественных зданий: target обновляется только для первых count экземпляров

        Returns:
            list: список записей для БД с полями:
                  {name: str, index: int|None, max_target_level: int, type: str, action: str}
        """
        logger.debug("📋 Извлечение уникального списка зданий из конфига...")

        # Словарь для отслеживания зданий
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
                        'built_count': 0,
                        'total_count': 0,
                        'target_by_index': {},  # словарь {index: target_level}
                        'max_target': 0,  # для уникальных зданий
                        'type': btype,
                        'has_build_action': False
                    }

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ
                if action == 'upgrade':
                    # Если уже встречался action='build', НЕ увеличиваем built_count!
                    if not buildings_tracking[name]['has_build_action']:
                        if count > buildings_tracking[name]['built_count']:
                            buildings_tracking[name]['built_count'] = count

                    # 🆕 ИСПРАВЛЕНО: Проверяем ТИП здания, а не count!
                    if btype == 'multiple':
                        # Множественное здание - обновляем target для первых count экземпляров
                        for index in range(1, count + 1):
                            # Обновляем target только если новый больше
                            current_target = buildings_tracking[name]['target_by_index'].get(index, 0)
                            if target > current_target:
                                buildings_tracking[name]['target_by_index'][index] = target
                    else:
                        # Уникальное здание
                        if target > buildings_tracking[name]['max_target']:
                            buildings_tracking[name]['max_target'] = target

                elif action == 'build':
                    # Строятся НОВЫЕ экземпляры
                    if count > buildings_tracking[name]['total_count']:
                        buildings_tracking[name]['total_count'] = count

                    # Отмечаем что встретили action='build'
                    buildings_tracking[name]['has_build_action'] = True

                    # Для новопостроенных зданий устанавливаем target
                    if btype == 'multiple':
                        # Множественное здание
                        for index in range(buildings_tracking[name]['built_count'] + 1, count + 1):
                            # Новые экземпляры (еще не построенные)
                            if index not in buildings_tracking[name]['target_by_index']:
                                buildings_tracking[name]['target_by_index'][index] = target
                    else:
                        # Уникальное здание
                        if target > buildings_tracking[name]['max_target']:
                            buildings_tracking[name]['max_target'] = target

                # Обновляем общее количество
                if count > buildings_tracking[name]['total_count']:
                    buildings_tracking[name]['total_count'] = count

        # Формируем результат
        result = []

        for name, data in buildings_tracking.items():
            built_count = data['built_count']
            total_count = data['total_count']
            target_by_index = data['target_by_index']
            max_target = data['max_target']
            btype = data['type']
            has_build_action = data['has_build_action']

            if total_count > 1:
                # Множественное здание - создаем запись для каждого экземпляра
                for index in range(1, total_count + 1):
                    # КЛЮЧЕВАЯ ЛОГИКА:
                    # Если индекс <= built_count → здание УЖЕ ПОСТРОЕНО (action='upgrade')
                    # Если индекс > built_count → здание НУЖНО ПОСТРОИТЬ (action='build')
                    instance_action = 'upgrade' if index <= built_count else 'build'

                    # Получаем ПЕРСОНАЛЬНЫЙ target для этого экземпляра
                    instance_target = target_by_index.get(index, 1)

                    result.append({
                        'name': name,
                        'index': index,
                        'max_target_level': instance_target,
                        'type': btype,
                        'action': instance_action
                    })
            else:
                # Уникальное здание
                unique_action = 'build' if has_build_action else 'upgrade'

                result.append({
                    'name': name,
                    'index': None,
                    'max_target_level': max_target,
                    'type': btype,
                    'action': unique_action
                })

        logger.info(f"✅ Найдено {len(result)} записей зданий")

        # Дебаг: выводим первые 10 записей
        logger.debug(f"\n📋 Первые 10 записей:")
        for i, b in enumerate(result[:10], 1):
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
        with self.db_lock:
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

        ИЗМЕНЕНИЕ v2: Добавлена ФАЗА 2 — верификация непостроенных зданий.
        После стандартного скана проверяет здания с action='build',
        чьё требование по уровню Лорда ≤ текущего. Если здание уже
        построено на ферме — обновляет БД (action → 'upgrade').

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
        logger.info(
            f"[{emulator_name}] 📋 Найдено зданий для сканирования: {total}"
        )

        if skipped_build:
            logger.info(
                f"[{emulator_name}] ⏭️ Пропущено непостроенных зданий: "
                f"{len(skipped_build)}"
            )

        # ═══════════════════════════════════════════════════
        # ФАЗА 1: Стандартное сканирование (action='upgrade')
        # ═══════════════════════════════════════════════════

        # ✅ FIX: Счётчики вынесены НАРУЖУ — доступны и в финальных итогах
        total_success_count = 0
        total_failed_count = 0

        if total == 0:
            logger.info(f"[{emulator_name}] ✅ Нет зданий для сканирования")
            # НЕ возвращаем сразу — переходим к фазе 2!
        else:
            # 3. Сгруппировать здания по разделам
            groups = self._group_buildings_by_section(scannable)

            logger.info(
                f"[{emulator_name}] 📂 Разделов для сканирования: {len(groups)}"
            )

            # 4. Импортируем NavigationPanel
            from functions.building.navigation_panel import NavigationPanel
            nav_panel = NavigationPanel()

            # 5. Сканируем каждый раздел и СРАЗУ обновляем БД
            section_num = 0
            for section_key, buildings_in_section in groups.items():
                section_num += 1
                logger.info(
                    f"[{emulator_name}] 📂 [{section_num}/{len(groups)}] "
                    f"Раздел: {section_key}"
                )
                logger.debug(
                    f"[{emulator_name}]    Зданий в разделе: "
                    f"{len(buildings_in_section)}"
                )

                # Открыть панель навигации
                if not nav_panel.open_navigation_panel(emulator):
                    logger.error(
                        f"[{emulator_name}] ❌ Не удалось открыть панель навигации"
                    )
                    total_failed_count += len(buildings_in_section)
                    continue

                # Получить конфигурацию первого здания для навигации
                first_building_name = buildings_in_section[0][0]
                building_config = nav_panel.get_building_config(first_building_name)

                if not building_config:
                    logger.error(
                        f"[{emulator_name}] ❌ Конфиг не найден для "
                        f"{first_building_name}"
                    )
                    total_failed_count += len(buildings_in_section)
                    continue

                # Перейти к разделу
                if not self._navigate_to_section(
                        emulator, nav_panel, building_config
                ):
                    logger.error(
                        f"[{emulator_name}] ❌ Не удалось перейти к разделу"
                    )
                    total_failed_count += len(buildings_in_section)
                    continue

                # Небольшая пауза после навигации
                time.sleep(0.5)

                # Парсить все здания на экране
                from utils.image_recognition import get_screenshot
                screenshot = get_screenshot(emulator)
                if screenshot is None:
                    logger.error(
                        f"[{emulator_name}] ❌ Не удалось получить скриншот"
                    )
                    total_failed_count += len(buildings_in_section)
                    continue

                all_buildings_on_screen = nav_panel.ocr.parse_navigation_panel(
                    screenshot,
                    emulator_id=emulator_id
                )

                if not all_buildings_on_screen:
                    logger.warning(
                        f"[{emulator_name}] ⚠️ Не удалось распознать здания "
                        f"в разделе {section_key}"
                    )
                    total_failed_count += len(buildings_in_section)
                    continue

                logger.info(
                    f"[{emulator_name}]    Распознано зданий на экране: "
                    f"{len(all_buildings_on_screen)}"
                )

                # Логируем все распознанные здания для отладки
                for b in all_buildings_on_screen:
                    logger.debug(
                        f"[{emulator_name}]      📍 {b['name']} Lv.{b['level']}"
                    )

                # ═══════════════════════════════════════════════════
                # ✅ FIX: Правильное сопоставление зданий с экраном
                #
                # Для МНОЖЕСТВЕННЫХ зданий (Луг #1, #2, #3, #4):
                #   - Собираем ВСЕ совпадения на экране
                #   - Сортируем по Y (позиция сверху вниз = порядок в игре)
                #   - Выбираем по building_index
                #
                # Для УНИКАЛЬНЫХ зданий (Источник, Склад Травы):
                #   - Берём первое совпадение
                # ═══════════════════════════════════════════════════
                for building_name, building_index in buildings_in_section:
                    target_normalized = building_name.lower().replace(' ', '')

                    # Собираем ВСЕ совпадения (не break на первом!)
                    found_instances = [
                        b for b in all_buildings_on_screen
                        if target_normalized in b['name'].lower().replace(' ', '')
                    ]

                    if not found_instances:
                        logger.error(
                            f"[{emulator_name}] ❌ {building_name}"
                            f"{f' #{building_index}' if building_index else ''}"
                            f": не найдено на экране"
                        )
                        total_failed_count += 1
                        continue

                    # Сортируем по Y (порядок на экране = порядок в игре)
                    found_instances.sort(key=lambda b: b['y'])

                    if building_index is not None:
                        # МНОЖЕСТВЕННОЕ здание — выбираем по индексу
                        # Убираем дубликаты по уровню+Y (на случай OCR-артефактов)
                        seen = set()
                        unique_instances = []
                        for inst in found_instances:
                            key = (inst['level'], inst['y'])
                            if key not in seen:
                                seen.add(key)
                                unique_instances.append(inst)

                        logger.debug(
                            f"[{emulator_name}]    {building_name}: "
                            f"найдено {len(unique_instances)} уникальных экземпляров"
                        )

                        for i, inst in enumerate(unique_instances):
                            logger.debug(
                                f"[{emulator_name}]      "
                                f"[{i + 1}] Lv.{inst['level']} (Y: {inst['y']})"
                            )

                        idx = building_index - 1  # Индекс в БД с 1, в массиве с 0

                        if idx < len(unique_instances):
                            level = unique_instances[idx]['level']

                            if level is not None and level > 0:
                                self.update_building_level(
                                    emulator_id, building_name,
                                    building_index, level
                                )
                                total_success_count += 1
                            else:
                                logger.error(
                                    f"[{emulator_name}] ❌ {building_name} "
                                    f"#{building_index}: уровень = {level}"
                                )
                                total_failed_count += 1
                        else:
                            logger.error(
                                f"[{emulator_name}] ❌ {building_name} "
                                f"#{building_index}: индекс вне диапазона "
                                f"(найдено {len(unique_instances)} уникальных)"
                            )
                            total_failed_count += 1
                    else:
                        # УНИКАЛЬНОЕ здание — берём первое совпадение
                        level = found_instances[0]['level']

                        if level is not None and level > 0:
                            self.update_building_level(
                                emulator_id, building_name, None, level
                            )
                            total_success_count += 1
                        else:
                            logger.error(
                                f"[{emulator_name}] ❌ {building_name}: "
                                f"уровень = {level}"
                            )
                            total_failed_count += 1

                # Свернуть раздел после обработки
                self._cleanup_after_section_scan(emulator, nav_panel)
                time.sleep(0.3)

            # Итоги ФАЗЫ 1
            logger.info(f"[{emulator_name}] 📊 ИТОГО ФАЗА 1 (сканирование):")
            logger.info(
                f"[{emulator_name}]   ✅ Успешно: {total_success_count}"
            )
            logger.info(
                f"[{emulator_name}]   ❌ Ошибки: {total_failed_count}"
            )

        # ═══════════════════════════════════════════════════
        # ═══ ФАЗА 2 — Верификация непостроенных зданий
        # ═══════════════════════════════════════════════════

        if skipped_build:
            lord = self.get_building(emulator_id, "Лорд", None)
            lord_level = lord['current_level'] if lord and lord['current_level'] > 0 else 0

            if lord_level == 0:
                logger.warning(
                    f"[{emulator_name}] ⚠️ Уровень Лорда неизвестен (0), "
                    f"пропускаю верификацию непостроенных зданий"
                )
            else:
                buildings_to_verify = []
                skipped_high_lord = []

                for building_name, building_index in skipped_build:
                    required_lord = self._get_build_lord_level(building_name)

                    if required_lord is not None and required_lord <= lord_level:
                        buildings_to_verify.append((building_name, building_index))
                        logger.debug(
                            f"[{emulator_name}] 🔎 {building_name}: "
                            f"lord_req={required_lord} ≤ lord={lord_level} → "
                            f"проверяем"
                        )
                    else:
                        skipped_high_lord.append((building_name, building_index))
                        logger.debug(
                            f"[{emulator_name}] ⏭️ {building_name}: "
                            f"lord_req={required_lord} > lord={lord_level} → "
                            f"пропускаем"
                        )

                if buildings_to_verify:
                    logger.info(
                        f"[{emulator_name}] 🔍 ФАЗА 2: Верификация "
                        f"{len(buildings_to_verify)} потенциально "
                        f"построенных зданий "
                        f"(Лорд: {lord_level})"
                    )

                    verified = self._verify_unbuilt_buildings(
                        emulator, buildings_to_verify
                    )

                    if verified > 0:
                        logger.success(
                            f"[{emulator_name}] 🎉 Обнаружено {verified} "
                            f"уже построенных зданий!"
                        )
                else:
                    logger.info(
                        f"[{emulator_name}] ℹ️ Нет зданий для верификации "
                        f"(все требуют Лорда > {lord_level})"
                    )

                if skipped_high_lord:
                    logger.debug(
                        f"[{emulator_name}] ⏭️ Пропущено (высокий уровень "
                        f"Лорда): {len(skipped_high_lord)}"
                    )

        # ═══ Финальные итоги ═══
        if total > 0 and total_failed_count > 0:
            logger.warning(
                f"[{emulator_name}] ⚠️ Сканирование завершено с ошибками"
            )
            return total_success_count > 0

        logger.success(
            f"[{emulator_name}] ✅ ПЕРВИЧНОЕ СКАНИРОВАНИЕ ЗАВЕРШЕНО УСПЕШНО"
        )
        return True

    def _verify_unbuilt_buildings(
        self,
        emulator: dict,
        buildings_to_verify: List[Tuple[str, Optional[int]]]
    ) -> int:
        """
        Проверить, не построены ли уже здания с action='build'.

        Вызывается после стандартного первичного сканирования.
        Для каждого здания: навигация к разделу → OCR → поиск на экране.
        Если здание найдено с уровнем ≥ 1 → обновляем БД:
          action: 'build' → 'upgrade', current_level = найденный уровень.

        Args:
            emulator: Объект эмулятора
            buildings_to_verify: Список [(building_name, building_index), ...]

        Returns:
            int: Количество зданий, которые оказались уже построены
        """
        emulator_id = emulator.get('id', 0)
        emulator_name = emulator.get('name', f'Emulator-{emulator_id}')

        logger.info(
            f"[{emulator_name}] 🔍 ВЕРИФИКАЦИЯ НЕПОСТРОЕННЫХ ЗДАНИЙ: "
            f"{len(buildings_to_verify)} кандидатов"
        )

        from functions.building.navigation_panel import NavigationPanel
        from utils.image_recognition import get_screenshot

        nav_panel = NavigationPanel()
        verified_count = 0

        # Группируем по разделам навигации (чтобы не открывать один раздел дважды)
        groups = self._group_buildings_by_section(buildings_to_verify)

        logger.info(
            f"[{emulator_name}] 📂 Разделов для верификации: {len(groups)}"
        )

        for section_key, buildings_in_section in groups.items():
            logger.info(
                f"[{emulator_name}] 📂 Верификация раздела: {section_key} "
                f"({len(buildings_in_section)} зданий)"
            )

            # Открыть панель навигации
            if not nav_panel.open_navigation_panel(emulator):
                logger.error(
                    f"[{emulator_name}] ❌ Не удалось открыть панель навигации"
                )
                continue

            # Получить конфигурацию первого здания для навигации к разделу
            first_building_name = buildings_in_section[0][0]
            building_config = nav_panel.get_building_config(first_building_name)

            if not building_config:
                logger.error(
                    f"[{emulator_name}] ❌ Конфиг не найден для "
                    f"{first_building_name}"
                )
                continue

            # Навигация к разделу
            if not self._navigate_to_section(emulator, nav_panel, building_config):
                logger.error(
                    f"[{emulator_name}] ❌ Не удалось перейти к разделу "
                    f"{section_key}"
                )
                continue

            time.sleep(0.5)

            # Скриншот + OCR
            screenshot = get_screenshot(emulator)
            if screenshot is None:
                logger.error(
                    f"[{emulator_name}] ❌ Не удалось получить скриншот"
                )
                continue

            all_buildings_on_screen = nav_panel.ocr.parse_navigation_panel(
                screenshot, emulator_id=emulator_id
            )

            if not all_buildings_on_screen:
                logger.warning(
                    f"[{emulator_name}] ⚠️ Не распознано зданий в разделе "
                    f"{section_key}"
                )
                self._cleanup_after_section_scan(emulator, nav_panel)
                continue

            logger.debug(
                f"[{emulator_name}]    Распознано на экране: "
                f"{len(all_buildings_on_screen)}"
            )

            # Ищем каждое непостроенное здание среди распознанных
            for building_name, building_index in buildings_in_section:
                found = self._match_unbuilt_building(
                    emulator_name, building_name, building_index,
                    all_buildings_on_screen
                )

                if found is not None:
                    found_name, found_level = found

                    if found_level >= 1:
                        # Здание ПОСТРОЕНО! Обновляем БД
                        logger.success(
                            f"[{emulator_name}] ✅ {building_name} НАЙДЕНО "
                            f"с Lv.{found_level} — обновляю БД"
                        )
                        self.update_building_after_construction(
                            emulator_id, building_name, building_index,
                            actual_level=found_level
                        )
                        verified_count += 1

                    elif found_level == 0:
                        # Здание есть но не достроено (Lv.0) — оставляем как есть
                        logger.info(
                            f"[{emulator_name}] ⚠️ {building_name} найдено "
                            f"с Lv.0 (не достроено)"
                        )
                else:
                    logger.debug(
                        f"[{emulator_name}] ➖ {building_name} не найдено "
                        f"на экране (ещё не построено)"
                    )

            # Очистка навигации перед следующим разделом
            self._cleanup_after_section_scan(emulator, nav_panel)
            time.sleep(0.3)

        logger.info(
            f"[{emulator_name}] 📊 ИТОГО ВЕРИФИКАЦИИ: "
            f"{verified_count}/{len(buildings_to_verify)} зданий "
            f"оказались уже построены"
        )

        return verified_count

    def _match_unbuilt_building(
        self,
        emulator_name: str,
        building_name: str,
        building_index: Optional[int],
        buildings_on_screen: List[Dict]
    ) -> Optional[Tuple[str, int]]:
        """
        Найти непостроенное здание среди распознанных на экране.

        ИСПРАВЛЕНО: Exact match вместо substring.
        Substring "складлистьев" IN "складлистьевii" давал ложные
        совпадения — "Склад Листьев" матчился при поиске
        "Склад Листьев II".

        Стратегия:
        1. Exact match (нормализованные имена совпадают полностью)
        2. Если exact не нашёл — НЕ fallback на substring
           (лучше пропустить, чем записать неправильный уровень)

        Args:
            emulator_name: Имя эмулятора (для логов)
            building_name: Искомое название здания
            building_index: Индекс (для множественных) или None
            buildings_on_screen: Результат parse_navigation_panel()

        Returns:
            (found_name, found_level) или None если не найдено
        """
        target_normalized = building_name.lower().replace(' ', '')

        # Exact match — нормализованные имена должны совпадать ПОЛНОСТЬЮ
        matches = []
        for b in buildings_on_screen:
            screen_normalized = b['name'].lower().replace(' ', '')
            if target_normalized == screen_normalized:
                matches.append(b)

        if not matches:
            return None

        # Для уникальных зданий — берём первое совпадение
        if building_index is None:
            return (matches[0]['name'], matches[0]['level'])

        # Для множественных — выбираем по индексу (позиция сверху вниз)
        matches.sort(key=lambda b: b['y'])

        if building_index <= len(matches):
            match = matches[building_index - 1]
            return (match['name'], match['level'])

        # Индекс больше чем найдено — здание на другом экране/не существует
        return None

    def _cleanup_after_section_scan(self, emulator: dict, nav_panel) -> bool:
        """
        Очистка состояния навигации после сканирования раздела

        ОПТИМИЗИРОВАННАЯ ВЕРСИЯ - устанавливает флаги состояния

        Логика:
        1. Свернуть все открытые подвкладки/вкладки (если есть)
        2. Сделать 2 свайпа к началу списка
        3. Финальная проверка - если что-то открыто, свернуть
        4. Установить флаги: is_collapsed=True, is_scrolled_to_top=True
        5. Готово к сканированию следующего раздела

        Благодаря флагам следующий вызов _navigate_to_section
        НЕ будет делать лишних действий!

        Args:
            emulator: объект эмулятора
            nav_panel: объект NavigationPanel

        Returns:
            bool: True если успешно
        """
        emulator_name = emulator.get('name', f"id:{emulator.get('id', '?')}")

        logger.debug(f"[{emulator_name}] 🧹 Очистка после сканирования раздела...")

        # ШАГ 1: Свернуть все открытые разделы (если есть)
        logger.debug(f"[{emulator_name}] 📦 Сворачивание открытых разделов...")
        nav_panel.collapse_all_sections(emulator)
        time.sleep(0.3)

        # ШАГ 2: Свайп к началу списка (2 раза)
        logger.debug(f"[{emulator_name}] ⬆️ Свайп к началу списка...")
        metadata = nav_panel.config.get('metadata', {})
        scroll_to_top = metadata.get('scroll_to_top', [])
        nav_panel.execute_swipes(emulator, scroll_to_top)
        time.sleep(0.3)

        # ШАГ 3: Финальная проверка - есть ли открытые разделы?
        logger.debug(f"[{emulator_name}] 🔍 Финальная проверка разделов...")
        from utils.image_recognition import find_image
        arrow_down = find_image(emulator, nav_panel.TEMPLATES['arrow_down'], threshold=0.8)
        arrow_down_sub = find_image(emulator, nav_panel.TEMPLATES['arrow_down_sub'], threshold=0.8)

        if arrow_down is not None or arrow_down_sub is not None:
            logger.debug(f"[{emulator_name}] ⚠️ Обнаружены открытые разделы, сворачиваю...")
            nav_panel.collapse_all_sections(emulator)
            time.sleep(0.3)

        # ШАГ 4: ✅ КРИТИЧНО - Устанавливаем флаги состояния
        nav_panel.nav_state.mark_collapsed()
        nav_panel.nav_state.mark_scrolled_to_top()

        logger.success(f"[{emulator_name}] ✅ Очистка завершена, готов к следующему разделу")
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

        ОПТИМИЗИРОВАНО: Не делает полный reset с кликами и свайпами
        Использует флаги состояния (is_collapsed, is_scrolled_to_top)

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

        # ✅ ОПТИМИЗАЦИЯ: Проверяем флаги состояния
        # Если после cleanup всё уже свернуто - не делаем лишних действий
        if not nav_panel.nav_state.is_collapsed:
            logger.debug(f"[{emulator_name}] 📦 Обнаружены открытые разделы, сворачиваю...")
            nav_panel.collapse_all_sections(emulator)
            time.sleep(0.3)
        else:
            logger.debug(f"[{emulator_name}] ✅ Все разделы уже свернуты (пропускаю)")

        # Проверяем находимся ли в начале списка
        if not nav_panel.nav_state.is_scrolled_to_top:
            logger.debug(f"[{emulator_name}] ⬆️ Возвращаюсь в начало списка...")
            metadata = nav_panel.config.get('metadata', {})
            scroll_to_top = metadata.get('scroll_to_top', [])
            nav_panel.execute_swipes(emulator, scroll_to_top)
            nav_panel.nav_state.mark_scrolled_to_top()
            time.sleep(0.3)

            # КРИТИЧНО! Проверяем что всё свернуто после свайпов
            # Свайпы могут "вытащить" ранее свёрнутые разделы обратно
            from utils.image_recognition import find_image
            arrow_down = find_image(emulator, nav_panel.TEMPLATES['arrow_down'], threshold=0.8)
            arrow_down_sub = find_image(emulator, nav_panel.TEMPLATES['arrow_down_sub'], threshold=0.8)

            if arrow_down is not None or arrow_down_sub is not None:
                logger.warning(f"[{emulator_name}] ⚠️ Обнаружены открытые разделы после свайпов, сворачиваю...")
                nav_panel.collapse_all_sections(emulator)
                time.sleep(0.3)
            else:
                logger.debug(f"[{emulator_name}] ✅ Все разделы свернуты после свайпов")

        else:
            logger.debug(f"[{emulator_name}] ✅ Уже в начале списка (пропускаю свайпы)")

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

    def check_and_update_completed_buildings(self, emulator_id: int) -> int:
        """
        Проверить и обновить завершенные постройки

        Вызывается в начале каждого цикла строительства

        Returns:
            количество завершенных построек
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            current_time = datetime.now()

            # Находим все здания с истекшими таймерами
            cursor.execute("""
                SELECT id, building_name, building_index, upgrading_to_level, timer_finish
                FROM buildings 
                WHERE emulator_id = ? 
                AND status = 'upgrading' 
                AND timer_finish <= ?
            """, (emulator_id, current_time))

            completed = cursor.fetchall()

            for row in completed:
                building_id = row['id']
                building_name = row['building_name']
                building_index = row['building_index']
                new_level = row['upgrading_to_level']

                # Обновляем здание
                cursor.execute("""
                    UPDATE buildings 
                    SET current_level = ?,
                        upgrading_to_level = NULL,
                        status = 'idle',
                        timer_finish = NULL,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_level, building_id))

                display_name = building_name
                if building_index:
                    display_name += f" #{building_index}"

                logger.success(f"✅ Завершено: {display_name} → Lv.{new_level}")

            if completed:
                self.conn.commit()

                # Пересчёт индексов для затронутых множественных зданий
                affected_names = set()
                for row in completed:
                    if row['building_index'] is not None:
                        affected_names.add(row['building_name'])

                for name in affected_names:
                    self.recalculate_building_indices(emulator_id, name)

            return len(completed)

    def recalculate_building_indices(self, emulator_id: int, building_name: str):
        """
        Пересчитать building_index для группы множественных зданий
        после завершения улучшения.

        Правило сортировки игры:
        - Более низкие уровни — вверху (меньший индекс)
        - Среди одинаковых уровней — последнее улучшенное внизу (больший индекс)

        Аппроксимация: ORDER BY current_level ASC, last_updated ASC
        """
        with self.db_lock:
            cursor = self.conn.cursor()

            # Получаем все экземпляры этого здания
            cursor.execute("""
                SELECT id, building_index, current_level, last_updated
                FROM buildings
                WHERE emulator_id = ? AND building_name = ? AND building_index IS NOT NULL
                ORDER BY current_level ASC, last_updated ASC
            """, (emulator_id, building_name))

            rows = cursor.fetchall()

            if not rows:
                return

            # Проверяем нужен ли пересчёт
            needs_recalc = False
            for new_index, row in enumerate(rows, start=1):
                if row['building_index'] != new_index:
                    needs_recalc = True
                    break

            if not needs_recalc:
                return

            # Логируем текущее и новое состояние
            logger.info(f"🔄 Пересчёт индексов: {building_name} (emulator {emulator_id})")

            # Используем временные отрицательные индексы чтобы избежать UNIQUE constraint
            # (нельзя сменить index 1→2 если index 2 уже существует)
            for new_index, row in enumerate(rows, start=1):
                cursor.execute("""
                    UPDATE buildings 
                    SET building_index = ?
                    WHERE id = ?
                """, (-(new_index), row['id']))

            # Теперь ставим правильные положительные
            for new_index, row in enumerate(rows, start=1):
                old_index = row['building_index']
                if old_index != new_index:
                    logger.debug(f"   {building_name}: index {old_index} → {new_index} "
                               f"(Lv.{row['current_level']})")

                cursor.execute("""
                    UPDATE buildings 
                    SET building_index = ?
                    WHERE id = ?
                """, (new_index, row['id']))

            self.conn.commit()
            logger.success(f"✅ Индексы пересчитаны: {building_name}")

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
        with self.db_lock:
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
                               builder_slot: int, actual_level: Optional[int] = None):
        """Пометить здание как улучшающееся"""

        with self.db_lock:
            logger.warning(f"[DEBUG] set_building_upgrading вызван: {building_name} "
                           f"#{building_index}, slot={builder_slot}")
            cursor = self.conn.cursor()

            # Получаем текущее здание
            building = self.get_building(emulator_id, building_name, building_index)

            if not building:
                logger.error(f"❌ Здание не найдено: {building_name}")
                return

            logger.warning(f"[DEBUG] ДО обновления: status={building['status']}")

            building_id = building['id']
            current_level = building['current_level']

            # ✅ ИСПРАВЛЕНИЕ: Коррекция уровня если обнаружено расхождение с игрой
            if actual_level is not None and actual_level != current_level:
                logger.warning(f"⚠️ Коррекция уровня: БД={current_level}, факт={actual_level}")
                current_level = actual_level

            upgrading_to = current_level + 1

            # Обновляем статус здания + корректируем current_level
            if building_index is not None:
                cursor.execute("""
                    UPDATE buildings 
                    SET current_level = ?,
                        upgrading_to_level = ?,
                        status = 'upgrading',
                        timer_finish = ?,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE emulator_id = ? AND building_name = ? AND building_index = ?
                """, (current_level, upgrading_to, timer_finish, emulator_id, building_name, building_index))
            else:
                cursor.execute("""
                    UPDATE buildings 
                    SET current_level = ?,
                        upgrading_to_level = ?,
                        status = 'upgrading',
                        timer_finish = ?,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE emulator_id = ? AND building_name = ? AND building_index IS NULL
                """, (current_level, upgrading_to, timer_finish, emulator_id, building_name))

            # Занимаем строителя
            cursor.execute("""
                UPDATE builders 
                SET is_busy = 1,
                    building_id = ?,
                    finish_time = ?
                WHERE emulator_id = ? AND builder_slot = ?
            """, (building_id, timer_finish, emulator_id, builder_slot))

            self.conn.commit()

            # Логирование после обновления
            updated_building = self.get_building(emulator_id, building_name, building_index)
            logger.warning(f"[DEBUG] ПОСЛЕ обновления: status={updated_building['status']}, "
                           f"upgrading_to={updated_building['upgrading_to_level']}")

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
        with self.db_lock:
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

        ИСПРАВЛЕНО: Теперь сначала освобождает строителей с истекшими таймерами

        Returns:
            номер слота (1, 2, 3, 4) или None если все заняты
        """
        with self.db_lock:
            cursor = self.conn.cursor()

            # ✅ ДОБАВЛЕНО: Сначала проверяем и освобождаем строителей с истекшими таймерами
            current_time = datetime.now()

            cursor.execute("""
                SELECT builder_slot, building_id, finish_time 
                FROM builders 
                WHERE emulator_id = ? AND is_busy = 1 AND finish_time <= ?
            """, (emulator_id, current_time))

            expired_builders = cursor.fetchall()

            # Освобождаем истекших строителей и обновляем здания
            for row in expired_builders:
                builder_slot = row['builder_slot']
                building_id = row['building_id']
                finish_time = row['finish_time']

                logger.info(f"🔨 Строитель #{builder_slot} завершил работу (финиш: {finish_time})")

                # Освобождаем строителя
                cursor.execute("""
                    UPDATE builders 
                    SET is_busy = 0,
                        building_id = NULL,
                        finish_time = NULL
                    WHERE emulator_id = ? AND builder_slot = ?
                """, (emulator_id, builder_slot))

                # Обновляем статус здания
                if building_id:
                    # Получаем информацию о здании
                    cursor.execute("""
                        SELECT building_name, building_index, upgrading_to_level 
                        FROM buildings 
                        WHERE id = ?
                    """, (building_id,))

                    building_row = cursor.fetchone()

                    if building_row:
                        building_name = building_row['building_name']
                        building_index = building_row['building_index']
                        new_level = building_row['upgrading_to_level']

                        # Обновляем здание: level повышен, статус idle
                        cursor.execute("""
                            UPDATE buildings 
                            SET current_level = ?,
                                upgrading_to_level = NULL,
                                status = 'idle',
                                timer_finish = NULL,
                                last_updated = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (new_level, building_id))

                        display_name = building_name
                        if building_index:
                            display_name += f" #{building_index}"

                        logger.success(f"✅ Здание {display_name} достигло уровня {new_level}")

            # Коммитим все изменения
            if expired_builders:
                self.conn.commit()
                logger.info(f"🔄 Освобождено строителей: {len(expired_builders)}")

                # Пересчёт индексов для затронутых множественных зданий
                affected_names = set()
                for row in expired_builders:
                    if row['building_id']:
                        cursor.execute(
                            "SELECT building_name, building_index FROM buildings WHERE id = ?",
                            (row['building_id'],)
                        )
                        b_row = cursor.fetchone()
                        if b_row and b_row['building_index'] is not None:
                            affected_names.add(b_row['building_name'])

                for name in affected_names:
                    self.recalculate_building_indices(emulator_id, name)

            # ✅ ТЕПЕРЬ ищем свободный слот
            cursor.execute("""
                SELECT builder_slot 
                FROM builders 
                WHERE emulator_id = ? AND is_busy = 0
                ORDER BY builder_slot
                LIMIT 1
            """, (emulator_id,))

            row = cursor.fetchone()

            if row:
                return row['builder_slot']

            return None

    def free_builder(self, emulator_id: int, builder_slot: int):
        """
        Освободить строителя

        Args:
            emulator_id: ID эмулятора
            builder_slot: номер слота строителя
        """
        with self.db_lock:
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

    def _get_build_lord_level(self, building_name: str) -> Optional[int]:
        """
        Определить на каком уровне Лорда здание впервые появляется с action='build'.

        Проходит по building_order.yaml (lord_10 → lord_18) и ищет первое
        вхождение здания с action='build'. Это минимальный уровень Лорда,
        при котором здание МОЖЕТ быть уже построено на ферме.

        Args:
            building_name: Название здания (например "Склад Песка II")

        Returns:
            Уровень Лорда (10-18) или None если здание не найдено с action='build'
        """
        for level in range(10, 19):
            lord_key = f"lord_{level}"

            if lord_key not in self.building_config:
                continue

            config = self.building_config[lord_key]
            buildings_list = config.get('buildings', [])

            for building in buildings_list:
                if building.get('name') == building_name and \
                        building.get('action') == 'build':
                    return level

        return None

    def get_next_building_to_upgrade(self, emulator: dict, auto_scan: bool = True) -> Optional[Dict]:
        """
        Определить следующее здание для прокачки

        ИСПРАВЛЕНО (v2.2 - ПОЛНАЯ ВЕРСИЯ):
        - Использование building['action'] из БД вместо action из конфига
        - Сохранение всей оригинальной логики для count=1 и count>1
        - Проверка промежуточных зданий для Лорда
        - Правильная обработка зданий с action='build'

        ЛОГИКА для множественных зданий:
        - count > 1: качать ВСЕ экземпляры до target, выбирать с МИНИМАЛЬНЫМ уровнем
        - count = 1: качать ТОЛЬКО ОДНО здание до target, выбирать с МАКСИМАЛЬНЫМ уровнем
                     КРИТИЧНО: Если хотя бы один экземпляр улучшается или достиг target -
                     ПОЛНОСТЬЮ ПРОПУСТИТЬ это здание и перейти к следующему в YAML

        Args:
            emulator: объект эмулятора
            auto_scan: автоматически сканировать уровни если level=0

        Returns:
            dict с ключами: name, index, current_level, target_level, is_lord, action
            или None если все здания достигли целевого уровня
        """
        emulator_id = emulator.get('id', 0)
        emulator_name = emulator.get('name', f'Emulator-{emulator_id}')

        # 1. Получаем уровень Лорда
        lord = self.get_building(emulator_id, "Лорд", None)
        if not lord:
            logger.error(f"[{emulator_name}] ❌ Лорд не найден в БД")
            return None

        lord_level = lord['current_level']
        logger.debug(f"[{emulator_name}] Текущий уровень Лорда: {lord_level}")

        # 2. Проходим по конфигу в порядке
        lord_key = f"lord_{lord_level}"

        if lord_key not in self.building_config:
            logger.debug(f"[{emulator_name}] Конфиг для Лорд {lord_level} не найден")
            return None

        config = self.building_config[lord_key]
        buildings_list = config.get('buildings', [])

        # 3. Проходим по списку зданий
        for building_cfg in buildings_list:
            name = building_cfg['name']
            count = building_cfg.get('count', 1)
            target = building_cfg.get('target_level', 1)
            btype = building_cfg.get('type', 'unique')
            config_action = building_cfg.get('action', 'upgrade')  # ← action из конфига (НЕ используем!)

            # ПРОВЕРКА ПРОМЕЖУТОЧНЫХ ЗДАНИЙ только для Лорда
            if name == "Лорд":
                if not self._check_intermediate_buildings_ready(emulator_id, lord_level):
                    logger.debug(f"[{emulator_name}] ⏸️ Лорд: промежуточные здания не готовы, пропускаем")
                    continue  # ← Пропускаем Лорда, но проверяем остальные здания!

            # МНОЖЕСТВЕННОЕ ЗДАНИЕ (несколько экземпляров)
            if btype == 'multiple':
                candidates = []

                # СПЕЦИАЛЬНАЯ ЛОГИКА ДЛЯ count=1
                if count == 1:
                    # Получаем ВСЕ экземпляры этого здания из БД
                    cursor = self.conn.cursor()
                    cursor.execute("""
                        SELECT building_index, current_level, status, action
                        FROM buildings 
                        WHERE emulator_id = ? AND building_name = ? AND building_index IS NOT NULL
                        ORDER BY building_index
                    """, (emulator_id, name))

                    all_instances = cursor.fetchall()

                    if not all_instances:
                        logger.warning(f"[{emulator_name}] ⚠️ {name}: не найдено экземпляров в БД")
                        continue

                    # КЛЮЧЕВАЯ ПРОВЕРКА: Если хотя бы один экземпляр улучшается или достиг target
                    # - ПРОПУСТИТЬ это здание ПОЛНОСТЬЮ
                    has_upgrading = False
                    has_reached_target = False

                    for row in all_instances:
                        if row['status'] == 'upgrading':
                            has_upgrading = True
                            break
                        if row['current_level'] >= target:
                            has_reached_target = True

                    if has_upgrading:
                        logger.debug(
                            f"[{emulator_name}] ⏭️ {name}: один экземпляр уже улучшается (count=1), пропускаем")
                        continue

                    if has_reached_target:
                        logger.debug(f"[{emulator_name}] ⏭️ {name}: один экземпляр достиг target (count=1), пропускаем")
                        continue

                    # Проверяем все экземпляры и ищем с максимальным уровнем
                    for row in all_instances:
                        index = row['building_index']
                        current_level = row['current_level']
                        status = row['status']
                        building_action = row['action']  # ← action ИЗ БД!

                        # Если здание нужно построить - возвращаем его!
                        if building_action == 'build' and current_level == 0:
                            logger.debug(f"[{emulator_name}] 🏗️ {name} #{index}: требуется постройка")
                            return {
                                'name': name,
                                'index': index,
                                'current_level': 0,
                                'target_level': target,
                                'is_lord': False,
                                'action': 'build'
                            }

                        # Автосканирование если level=0 и action='upgrade'
                        if current_level == 0 and building_action == 'upgrade':
                            if auto_scan:
                                logger.warning(
                                    f"[{emulator_name}] ⚠️ {name} #{index}: уровень неизвестен, сканируем...")
                                success = self.scan_building_level(emulator, name, index)

                                if not success:
                                    logger.error(f"[{emulator_name}] ❌ Не удалось просканировать {name} #{index}")
                                    continue

                                # Обновляем данные
                                building = self.get_building(emulator_id, name, index)
                                current_level = building['current_level']
                                status = building['status']
                            else:
                                logger.warning(
                                    f"[{emulator_name}] ⚠️ {name} #{index}: уровень неизвестен (level=0), пропускаем")
                                continue

                        # Проверка уровня Лорда
                        if current_level + 1 > lord_level:
                            logger.debug(
                                f"[{emulator_name}] ⏸️ {name} #{index}: уровень {current_level + 1} > Лорд {lord_level}")
                            continue

                        # Добавляем кандидата (не проверяем status, т.к. уже проверили выше)
                        if current_level < target:
                            candidates.append({
                                'name': name,
                                'index': index,
                                'current_level': current_level,
                                'target_level': target,
                                'is_lord': (name == "Лорд"),
                                'action': building_action  # ← ИЗ БД!
                            })

                # ЛОГИКА ДЛЯ count>1
                else:
                    # Смотрим только первые count экземпляров
                    for index in range(1, count + 1):
                        building = self.get_building(emulator_id, name, index)

                        if not building:
                            logger.warning(f"[{emulator_name}] ⚠️ {name} #{index}: не найдено в БД")
                            continue

                        building_action = building['action']  # ← action ИЗ БД!
                        building_level = building['current_level']
                        building_status = building['status']

                        # Если здание нужно построить - возвращаем его!
                        if building_action == 'build' and building_level == 0:
                            logger.debug(f"[{emulator_name}] 🏗️ {name} #{index}: требуется постройка")
                            return {
                                'name': name,
                                'index': index,
                                'current_level': 0,
                                'target_level': target,
                                'is_lord': False,
                                'action': 'build'
                            }

                        # Автосканирование если level=0 и action='upgrade'
                        if building_level == 0 and building_action == 'upgrade':
                            if auto_scan:
                                logger.warning(
                                    f"[{emulator_name}] ⚠️ {name} #{index}: уровень неизвестен, сканируем...")
                                success = self.scan_building_level(emulator, name, index)

                                if not success:
                                    logger.error(f"[{emulator_name}] ❌ Не удалось просканировать {name} #{index}")
                                    continue

                                building = self.get_building(emulator_id, name, index)
                                building_level = building['current_level']
                                building_status = building['status']
                            else:
                                logger.warning(
                                    f"[{emulator_name}] ⚠️ {name} #{index}: уровень неизвестен (level=0), пропускаем")
                                continue

                        # Проверка уровня Лорда
                        if building_level + 1 > lord_level:
                            logger.debug(
                                f"[{emulator_name}] ⏸️ {name} #{index}: уровень {building_level + 1} > Лорд {lord_level}")
                            continue

                        # Добавляем кандидата
                        if (building_status != 'upgrading' and building_level < target):
                            candidates.append({
                                'name': name,
                                'index': index,
                                'current_level': building_level,
                                'target_level': target,
                                'is_lord': (name == "Лорд"),
                                'action': building_action  # ← ИЗ БД!
                            })

                # Выбираем лучшего кандидата
                if candidates:
                    if count == 1:
                        # Для count=1: выбираем с МАКСИМАЛЬНЫМ уровнем
                        best_candidate = max(candidates, key=lambda x: x['current_level'])
                        logger.debug(f"[{emulator_name}] ✅ Выбрано {name} #{best_candidate['index']} "
                                     f"(уровень {best_candidate['current_level']} - максимальный, качаем одно здание)")
                    else:
                        # Для count>1: выбираем с МИНИМАЛЬНЫМ уровнем
                        best_candidate = min(candidates, key=lambda x: x['current_level'])
                        logger.debug(f"[{emulator_name}] ✅ Выбрано {name} #{best_candidate['index']} "
                                     f"(уровень {best_candidate['current_level']} - минимальный среди доступных)")

                    return best_candidate

            # УНИКАЛЬНОЕ ЗДАНИЕ (один экземпляр)
            else:
                building = self.get_building(emulator_id, name, None)

                # Если здание не найдено в БД и требует постройки
                if not building:
                    if config_action == 'build':
                        if self._can_construct_building(emulator_id, name):
                            return {
                                'name': name,
                                'index': None,
                                'current_level': 0,
                                'target_level': target,
                                'is_lord': (name == "Лорд"),
                                'action': 'build'  # ← Здесь можем использовать 'build' т.к. здания нет в БД
                            }
                    continue

                building_action = building['action']  # ← action ИЗ БД!
                building_level = building['current_level']
                building_status = building['status']

                # Если здание нужно построить - возвращаем его!
                if building_action == 'build' and building_level == 0:
                    logger.debug(f"[{emulator_name}] 🏗️ {name}: требуется постройка")
                    return {
                        'name': name,
                        'index': None,
                        'current_level': 0,
                        'target_level': target,
                        'is_lord': (name == "Лорд"),
                        'action': 'build'
                    }

                # Автосканирование если level=0 и action='upgrade'
                if building_level == 0 and building_action == 'upgrade':
                    if auto_scan:
                        logger.warning(f"[{emulator_name}] ⚠️ {name}: уровень неизвестен, сканируем...")
                        success = self.scan_building_level(emulator, name, None)

                        if not success:
                            logger.error(f"[{emulator_name}] ❌ Не удалось просканировать {name}")
                            continue

                        building = self.get_building(emulator_id, name, None)
                        building_level = building['current_level']
                        building_status = building['status']
                    else:
                        logger.warning(f"[{emulator_name}] ⚠️ {name}: уровень неизвестен (level=0), пропускаем")
                        continue

                # Проверка уровня Лорда
                if building_level + 1 > lord_level:
                    logger.debug(f"[{emulator_name}] ⏸️ {name}: уровень {building_level + 1} > Лорд {lord_level}")
                    continue

                # Возвращаем уникальное здание
                if (building_status != 'upgrading' and building_level < target):
                    return {
                        'name': name,
                        'index': None,
                        'current_level': building_level,
                        'target_level': target,
                        'is_lord': (name == "Лорд"),
                        'action': building_action  # ← ИЗ БД!
                    }

        # 4. Все здания достигли целевого уровня
        return None

    def update_building_after_construction(self, emulator_id: int, building_name: str,
                                           building_index: Optional[int] = None,
                                           actual_level: Optional[int] = None) -> None:
        """
        Обновить здание после успешной постройки

        ИСПРАВЛЕНО: Теперь принимает actual_level для корректного обновления

        Изменения:
        1. Установить current_level = actual_level (или 1 если не передан)
        2. Изменить action: 'build' → 'upgrade'
        3. Обновить last_updated

        Args:
            emulator_id: ID эмулятора
            building_name: название здания
            building_index: индекс (для множественных зданий)
            actual_level: фактический уровень здания (по умолчанию 1)
        """
        with self.db_lock:
            cursor = self.conn.cursor()

            building_display = f"{building_name}" + (f" #{building_index}" if building_index else "")

            # Если actual_level не передан, используем 1
            level_to_set = actual_level if actual_level is not None else 1

            if building_index is None:
                # Unique здание
                cursor.execute("""
                    UPDATE buildings 
                    SET current_level = ?,
                        action = 'upgrade',
                        last_updated = CURRENT_TIMESTAMP
                    WHERE emulator_id = ? AND building_name = ? AND building_index IS NULL
                """, (level_to_set, emulator_id, building_name))
            else:
                # Multiple здание
                cursor.execute("""
                    UPDATE buildings 
                    SET current_level = ?,
                        action = 'upgrade',
                        last_updated = CURRENT_TIMESTAMP
                    WHERE emulator_id = ? AND building_name = ? AND building_index = ?
                """, (level_to_set, emulator_id, building_name, building_index))

            self.conn.commit()

            logger.success(f"[Emulator {emulator_id}] ✅ {building_display} построено!")
            logger.info(f"[Emulator {emulator_id}] 🔄 Action: 'build' → 'upgrade', Level: 0 → {level_to_set}")

    # ===== ЗАМОРОЗКА ЭМУЛЯТОРА =====

    def freeze_emulator(self, emulator_id: int, hours: int = 4, reason: str = "Нехватка ресурсов"):
        """
        Заморозить функцию СТРОИТЕЛЬСТВА на эмуляторе

        ОБНОВЛЕНО: Теперь использует таблицу function_freeze
        вместо emulator_freeze. Замораживает ТОЛЬКО строительство,
        не влияя на эволюцию и другие функции.

        Args:
            emulator_id: ID эмулятора
            hours: количество часов заморозки
            reason: причина заморозки

        Заморозить СТРОИТЕЛЬСТВО — делегирует единому менеджеру
        """
        function_freeze_manager.freeze(
            emulator_id=emulator_id,
            function_name='building',
            hours=hours,
            reason=reason
        )

    def is_emulator_frozen(self, emulator_id: int) -> bool:
        """Проверить заморожено ли СТРОИТЕЛЬСТВО — делегирует единому менеджеру"""
        return function_freeze_manager.is_frozen(emulator_id, 'building')

    def unfreeze_emulator(self, emulator_id: int):
        """Разморозить СТРОИТЕЛЬСТВО — делегирует единому менеджеру"""
        function_freeze_manager.unfreeze(emulator_id, 'building')

    # ===== МЕТОДЫ ДЛЯ ПЛАНИРОВЩИКА =====

    def has_buildings(self, emulator_id: int) -> bool:
        """
        Есть ли записи зданий для эмулятора в БД

        Используется планировщиком для определения НОВЫХ эмуляторов:
        - False → эмулятор новый, требуется первичное сканирование
        - True → эмулятор уже инициализирован

        Args:
            emulator_id: ID эмулятора

        Returns:
            bool: True если есть хотя бы одна запись
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM buildings WHERE emulator_id = ?",
                (emulator_id,)
            )
            return cursor.fetchone()[0] > 0

    def has_buildings_to_upgrade(self, emulator_id: int) -> bool:
        """
        Есть ли здания которые можно улучшить или построить

        Проверяет наличие зданий со статусом 'idle' которые
        ещё не достигли целевого уровня.

        Условия для включения:
        - status = 'idle' (не в процессе улучшения)
        - current_level < target_level (есть куда расти)

        НЕ учитывает:
        - Наличие свободных строителей (это отдельная проверка)
        - Наличие ресурсов (узнаем только при попытке улучшения)
        - Автосканирование (это делается при запуске эмулятора)

        Args:
            emulator_id: ID эмулятора

        Returns:
            bool: True если есть хотя бы одно такое здание
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM buildings
                WHERE emulator_id = ?
                AND status = 'idle'
                AND current_level < target_level
            """, (emulator_id,))
            return cursor.fetchone()[0] > 0

    def get_nearest_builder_finish_time(self, emulator_id: int) -> Optional[datetime]:
        """
        Время ближайшего освобождения занятого строителя

        Используется планировщиком для определения когда эмулятору
        потребуется внимание (когда освободится строитель).

        Проверяет ТОЛЬКО занятых строителей (is_busy = 1) с установленным
        finish_time. Если все строители свободны — возвращает None.

        Args:
            emulator_id: ID эмулятора

        Returns:
            datetime — время ближайшего освобождения
            None — нет занятых строителей (все свободны или нет записей)
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT MIN(finish_time) as nearest
                FROM builders
                WHERE emulator_id = ? AND is_busy = 1 AND finish_time IS NOT NULL
            """, (emulator_id,))

            row = cursor.fetchone()

            if row and row['nearest']:
                finish_time = row['nearest']
                # SQLite может хранить как строку — обрабатываем оба варианта
                if isinstance(finish_time, str):
                    return datetime.fromisoformat(finish_time)
                return finish_time

            return None

    def get_all_builder_finish_times(self, emulator_id: int) -> list:
        """
        Все времена освобождения занятых строителей (для батчинга)

        Используется планировщиком для определения оптимального
        момента запуска. Если два строителя освобождаются с разницей
        в несколько минут — лучше подождать и обработать оба за раз.

        Возвращает только будущие времена (finish_time > now).
        Строители с истёкшими таймерами уже свободны (обрабатываются
        в get_free_builder()).

        Args:
            emulator_id: ID эмулятора

        Returns:
            list[datetime] — отсортированный по возрастанию, может быть пустым
        """
        with self.db_lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT finish_time
                FROM builders
                WHERE emulator_id = ? AND is_busy = 1 AND finish_time IS NOT NULL
                ORDER BY finish_time ASC
            """, (emulator_id,))

            times = []
            for row in cursor.fetchall():
                finish_time = row['finish_time']
                if isinstance(finish_time, str):
                    times.append(datetime.fromisoformat(finish_time))
                elif finish_time:
                    times.append(finish_time)

            return times

    def get_freeze_until(self, emulator_id: int):
        """Время разморозки строительства"""
        return function_freeze_manager.get_unfreeze_time(emulator_id, 'building')