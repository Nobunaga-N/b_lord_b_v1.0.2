"""
База данных для хранения состояния зданий и строителей
Управление прокачкой зданий через SQLite

Версия: 1.1 (ИСПРАВЛЕННАЯ)
Дата обновления: 2025-01-17
Изменения:
- Добавлен метод _can_construct_building() для проверки условий постройки
- Исправлен get_next_building_to_upgrade() с проверкой уровня Лорда
"""

import os
import sqlite3
import yaml
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

        # Таблица зданий
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
        logger.debug("✅ Таблицы БД созданы/проверены")

    def _load_building_config(self):
        """Загрузить конфигурацию порядка прокачки из YAML"""
        if not os.path.exists(self.CONFIG_PATH):
            logger.error(f"❌ Конфиг не найден: {self.CONFIG_PATH}")
            self.building_config = {}
            return

        with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
            self.building_config = yaml.safe_load(f)

        logger.debug(f"✅ Конфигурация загружена: {len(self.building_config)} уровней Лорда")

    # ===== РАБОТА С ЗАМОРОЗКОЙ =====

    def is_emulator_frozen(self, emulator_id: int) -> bool:
        """Проверить заморожен ли эмулятор"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT freeze_until FROM emulator_freeze 
            WHERE emulator_id = ? AND freeze_until > CURRENT_TIMESTAMP
        """, (emulator_id,))
        return cursor.fetchone() is not None

    def freeze_emulator(self, emulator_id: int, hours: int = 6, reason: str = "Недостаточно ресурсов"):
        """Заморозить эмулятор на N часов"""
        cursor = self.conn.cursor()
        freeze_until = datetime.now() + timedelta(hours=hours)

        cursor.execute("""
            INSERT OR REPLACE INTO emulator_freeze (emulator_id, freeze_until, reason)
            VALUES (?, ?, ?)
        """, (emulator_id, freeze_until, reason))

        self.conn.commit()
        logger.warning(f"❄️ Эмулятор {emulator_id} заморожен до {freeze_until.strftime('%Y-%m-%d %H:%M')}")

    def unfreeze_emulator(self, emulator_id: int):
        """Разморозить эмулятор"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM emulator_freeze WHERE emulator_id = ?", (emulator_id,))
        self.conn.commit()
        logger.info(f"✅ Эмулятор {emulator_id} разморожен")

    def get_freeze_info(self, emulator_id: int) -> Optional[Dict]:
        """Получить информацию о заморозке"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM emulator_freeze WHERE emulator_id = ?
        """, (emulator_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # ===== ИНИЦИАЛИЗАЦИЯ ЭМУЛЯТОРА =====

    def init_emulator_buildings(self, emulator_id: int, buildings_data: List[Dict]):
        """
        Инициализировать здания для эмулятора (первый запуск)

        Args:
            emulator_id: ID эмулятора
            buildings_data: список словарей с полями name, level, index
        """
        cursor = self.conn.cursor()

        logger.info(f"🏗️ Инициализация зданий для эмулятора {emulator_id}")

        for building_data in buildings_data:
            name = building_data['name']
            level = building_data['level']
            index = building_data.get('index')

            # Ищем здание в конфиге чтобы определить target_level и type
            building_info = self._find_building_in_config(name)

            if not building_info:
                logger.warning(f"⚠️ Здание '{name}' не найдено в конфиге, пропускаем")
                continue

            btype = building_info['type']
            target = building_info['target_level']

            # Вставляем или обновляем запись
            cursor.execute("""
                INSERT OR REPLACE INTO buildings 
                (emulator_id, building_name, building_type, building_index, 
                 current_level, target_level, status, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, 'idle', CURRENT_TIMESTAMP)
            """, (emulator_id, name, btype, index, level, target))

        self.conn.commit()
        logger.success(f"✅ Инициализировано {len(buildings_data)} зданий")

    def init_emulator_builders(self, emulator_id: int, slots: int = 3):
        """
        Создать записи для строителей

        Args:
            emulator_id: ID эмулятора
            slots: количество слотов строителей (3 или 4)
        """
        cursor = self.conn.cursor()

        logger.info(f"🔨 Инициализация {slots} строителей для эмулятора {emulator_id}")

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

    # ===== РАБОТА С ЗДАНИЯМИ =====

    def get_building(self, emulator_id: int, building_name: str,
                     building_index: Optional[int] = None) -> Optional[Dict]:
        """
        Получить информацию о здании

        Returns:
            dict с полями: id, name, type, index, current_level, upgrading_to_level,
                          target_level, status, timer_finish
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

        if not row:
            return None

        return dict(row)

    def get_lord_level(self, emulator_id: int) -> int:
        """Получить текущий уровень Лорда"""
        lord = self.get_building(emulator_id, "Лорд")

        if not lord:
            logger.warning(f"⚠️ Лорд не найден для эмулятора {emulator_id}, устанавливаем 10")
            return 10

        return lord['current_level']

    def update_building_level(self, emulator_id: int, building_name: str,
                              new_level: int, building_index: Optional[int] = None):
        """Обновить уровень здания после завершения постройки"""
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
        logger.info(f"⏳ Здание улучшается: {building_name} {current_level}→{upgrading_to}")

    def check_finished_buildings(self, emulator_id: int) -> List[Dict]:
        """
        Проверить какие здания завершили улучшение

        Returns:
            список зданий где timer_finish <= now
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT * FROM buildings 
            WHERE emulator_id = ? 
            AND status = 'upgrading' 
            AND timer_finish <= CURRENT_TIMESTAMP
        """, (emulator_id,))

        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def complete_building(self, emulator_id: int, building_id: int):
        """
        Завершить постройку здания

        - Увеличить current_level
        - Сбросить upgrading_to_level и timer_finish
        - Освободить строителя
        - Проверить достижение target_level
        """
        cursor = self.conn.cursor()

        # Получаем информацию о здании
        cursor.execute("SELECT * FROM buildings WHERE id = ?", (building_id,))
        building = dict(cursor.fetchone())

        new_level = building['upgrading_to_level']
        target_level = building['target_level']

        # Определяем новый статус
        new_status = 'target_reached' if new_level >= target_level else 'idle'

        # Обновляем здание
        cursor.execute("""
            UPDATE buildings 
            SET current_level = ?,
                upgrading_to_level = NULL,
                status = ?,
                timer_finish = NULL,
                last_updated = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_level, new_status, building_id))

        # Освобождаем строителя
        cursor.execute("""
            UPDATE builders 
            SET is_busy = 0,
                building_id = NULL,
                finish_time = NULL
            WHERE emulator_id = ? AND building_id = ?
        """, (emulator_id, building_id))

        self.conn.commit()

        status_emoji = "🎯" if new_status == 'target_reached' else "✅"
        logger.info(f"{status_emoji} Постройка завершена: {building['building_name']} → {new_level} ур")

    # ===== РАБОТА СО СТРОИТЕЛЯМИ =====

    def get_free_builders_count(self, emulator_id: int) -> int:
        """Получить количество свободных строителей"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM builders 
            WHERE emulator_id = ? AND is_busy = 0
        """, (emulator_id,))
        return cursor.fetchone()[0]

    def get_free_builder_slot(self, emulator_id: int) -> Optional[int]:
        """Получить номер первого свободного слота"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT builder_slot FROM builders 
            WHERE emulator_id = ? AND is_busy = 0
            ORDER BY builder_slot
            LIMIT 1
        """, (emulator_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def add_builder_slot(self, emulator_id: int):
        """Добавить 4-й слот строителя (после постройки Жилища Лемуров IV)"""
        cursor = self.conn.cursor()

        # Проверяем есть ли уже 4-й слот
        cursor.execute("""
            SELECT COUNT(*) FROM builders 
            WHERE emulator_id = ? AND builder_slot = 4
        """, (emulator_id,))

        if cursor.fetchone()[0] > 0:
            logger.info("ℹ️ 4-й строитель уже добавлен")
            return

        # Добавляем 4-й слот
        cursor.execute("""
            INSERT INTO builders (emulator_id, builder_slot, is_busy)
            VALUES (?, 4, 0)
        """, (emulator_id,))

        self.conn.commit()
        logger.success("✅ Добавлен 4-й слот строителя!")

    # ===== УСЛОВИЯ ПОСТРОЙКИ НОВЫХ ЗДАНИЙ (НОВЫЙ МЕТОД) =====

    def _can_construct_building(self, emulator_id: int, building_name: str) -> bool:
        """
        Проверить можно ли построить здание

        Условия постройки:
        - Жилище Лемуров IV: Лорд >= 13
        - Центр Сбора II: Лорд >= 13
        - Центр Сбора III: Лорд >= 18
        - Склад X II: Лорд >= 13 И Склад X >= 10
        - Жилище Детенышей (5-е): Лорд >= 14

        Returns:
            True если все условия выполнены
        """
        lord_level = self.get_lord_level(emulator_id)

        # Жилище Лемуров IV
        if building_name == "Жилище Лемуров IV":
            return lord_level >= 13

        # Центр Сбора II
        if building_name == "Центр Сбора II":
            return lord_level >= 13

        # Центр Сбора III
        if building_name == "Центр Сбора III":
            return lord_level >= 18

        # Жилище Детенышей (5-е)
        if "Жилище Детенышей" in building_name:
            return lord_level >= 14

        # Склады II: Лорд >= 13 И обычный склад >= 10
        if "Склад" in building_name and "II" in building_name:
            if lord_level < 13:
                logger.debug(f"📌 {building_name}: Лорд {lord_level} < 13")
                return False

            # Маппинг склада II → обычный склад
            resource_map = {
                "Склад Фруктов II": "Склад Фруктов",
                "Склад Листьев II": "Склад Листьев",
                "Склад Грунта II": "Склад Грунта",
                "Склад Песка II": "Склад Песка",
            }

            base_warehouse = resource_map.get(building_name)
            if base_warehouse:
                base = self.get_building(emulator_id, base_warehouse, None)
                if not base or base['current_level'] < 10:
                    logger.debug(f"📌 {building_name}: {base_warehouse} уровень {base['current_level'] if base else 0} < 10")
                    return False

            return True

        # По умолчанию можно строить
        return True

    # ===== ЛОГИКА ПРОКАЧКИ (ИСПРАВЛЕННЫЙ МЕТОД) =====

    def get_next_building_to_upgrade(self, emulator_id: int) -> Optional[Dict]:
        """
        ГЛАВНЫЙ МЕТОД - определить следующее здание для прокачки

        ИСПРАВЛЕНО:
        - Добавлена проверка уровня Лорда (нельзя улучшать здания выше уровня Лорда)
        - Добавлена проверка условий постройки для новых зданий

        Алгоритм:
        1. Получить уровень Лорда
        2. Загрузить конфиг для этого уровня
        3. Пройти по списку зданий по порядку
        4. Проверить: нельзя улучшать здания выше уровня Лорда
        5. Проверить условия постройки для новых зданий
        6. Найти первое здание которое нужно качать

        Returns:
            {
                'name': 'Улей',
                'index': 2,
                'current_level': 8,
                'target_level': 10,
                'is_lord': False,
                'action': 'upgrade' или 'construct'
            }
            или None если всё готово
        """
        # 1. Получить текущий уровень Лорда
        lord_level = self.get_lord_level(emulator_id)

        # 2. Загрузить конфиг для текущего уровня
        config_key = f"lord_{lord_level}"
        config = self.building_config.get(config_key)

        if not config:
            logger.error(f"❌ Нет конфига для {config_key}")
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

                    # КРИТИЧЕСКАЯ ПРОВЕРКА: нельзя улучшать выше уровня Лорда
                    if building['current_level'] + 1 > lord_level:
                        logger.debug(f"⏸️ {name} #{index}: уровень {building['current_level']+1} > Лорд {lord_level}")
                        continue

                    # Проверяем: не улучшается ли + не достигло target
                    if (building['status'] != 'upgrading' and
                            building['current_level'] < target):
                        return {
                            'name': name,
                            'index': index,
                            'current_level': building['current_level'],
                            'target_level': target,
                            'is_lord': False,
                            'action': action
                        }

            # 5. Если уникальное здание
            else:
                building = self.get_building(emulator_id, name)

                if not building:
                    # Здание не существует - нужно построить
                    if action == 'build':
                        # Проверяем условия постройки
                        if self._can_construct_building(emulator_id, name):
                            return {
                                'name': name,
                                'index': None,
                                'current_level': 0,
                                'target_level': target,
                                'is_lord': (name == "Лорд"),
                                'action': 'construct'
                            }
                        else:
                            # Условия не выполнены, пропускаем
                            logger.debug(f"⏸️ {name}: условия постройки не выполнены")
                            continue
                    continue

                # КРИТИЧЕСКАЯ ПРОВЕРКА: нельзя улучшать выше уровня Лорда
                # (кроме самого Лорда)
                if name != "Лорд" and building['current_level'] + 1 > lord_level:
                    logger.debug(f"⏸️ {name}: уровень {building['current_level']+1} > Лорд {lord_level}")
                    continue

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

        # 6. Все здания на текущем уровне готовы
        # Проверяем есть ли следующий уровень
        next_level = lord_level + 1
        next_config_key = f"lord_{next_level}"
        next_config = self.building_config.get(next_config_key)

        if not next_config:
            # Достигли максимума (lord_18 завершён)
            logger.info(f"🎉 Эмулятор {emulator_id} завершил все постройки!")
            return None

        # 7. Первое здание в следующем конфиге - Лорд
        first_building = next_config['buildings'][0]

        if first_building['name'] != "Лорд":
            logger.error(f"❌ Ошибка конфига: первое здание в {next_config_key} не Лорд!")
            return None

        # 8. Возвращаем Лорда для прокачки
        lord = self.get_building(emulator_id, "Лорд")

        return {
            'name': "Лорд",
            'index': None,
            'current_level': lord['current_level'],
            'target_level': first_building['target_level'],
            'is_lord': True,
            'action': 'upgrade'
        }

    def can_build_new_buildings(self, emulator_id: int) -> bool:
        """
        Проверка: можно ли строить НОВЫЕ здания?

        Вызывается из планировщика чтобы понять нужно ли включать эмулятор
        """
        next_building = self.get_next_building_to_upgrade(emulator_id)

        if not next_building:
            return False

        # Если следующее действие - постройка
        return next_building.get('action') == 'construct'