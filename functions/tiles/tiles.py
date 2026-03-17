"""
Функция: TilesFunction — сбор ресурсов с плиток

Отправка отрядов на плитки карты мира для сбора ресурсов.
Запускается ТОЛЬКО после успешного завершения автоохоты на диких.

Переиспользуемые компоненты:
- WildsNavigation       — ensure_on_world_map(), ensure_in_estate(),
                          setup_formation_sheet() (для возврата на Лист 1)
- WildsResourceManager  — _parse_all_storages() (парсинг складов)
- TilesNavigation       — send_squad_to_tile(), setup_sheet_2()
- TilesDistributor      — distribute() (распределение отрядов по ресурсам)

Контракт execute():
- return True  = ситуация обработана (включая заморозку, пустые списки и т.д.)
- return False = критическая ошибка навигации → автозаморозка через run()

Версия: 1.0
Дата создания: 2025-03-17
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from functions.base_function import BaseFunction
from functions.wilds.wilds_navigation import WildsNavigation
from functions.wilds.wilds_resource_manager import WildsResourceManager
from functions.tiles.tiles_navigation import TilesNavigation
from functions.tiles.tiles_distributor import TilesDistributor, RESOURCE_NAMES_RU
from utils.config_manager import load_config
from utils.function_freeze_manager import function_freeze_manager
from utils.logger import logger


# Ресурсы, доступные на плитках (без мёда)
TILE_RESOURCES = ['apples', 'leaves', 'soil', 'sand']

# Порядок отрядов (для загрузки из GUI)
SQUAD_KEYS = ['special', 'squad_1', 'squad_2', 'squad_3']

# Русские названия отрядов для логов
SQUAD_NAMES_RU = {
    'special': 'Особый Отряд',
    'squad_1': 'Отряд I',
    'squad_2': 'Отряд II',
    'squad_3': 'Отряд III',
}


class TilesFunction(BaseFunction):
    """
    Оркестратор сбора ресурсов с плиток

    Цикл execute():
    1. Загрузить настройки (ресурсы, отряды, уровни)
    2. Вернуться в поместье → спарсить склады
    3. Распределить отряды по ресурсам (TilesDistributor)
    4. Выйти на карту мира → настроить Лист 2 (если нужно)
    5. Для каждого assignment: лупа → поиск → ресурс → отряд → отправить
    6. Вернуть Лист 1 (если переключали)
    7. Вернуться в поместье

    session_state['tiles']:
    {
        'sent_this_session': bool,      — уже отправляли в этой сессии?
        'tuesday_visited': [str, ...],  — посещённые ресурсы (вторник) [только в памяти,
                                          основной трекинг в БД через TilesDistributor]
    }
    """

    FUNCTION_NAME = 'tiles'

    def __init__(self, emulator, session_state=None):
        super().__init__(emulator, session_state)
        self.name = "TilesFunction"

        # Подмодули (ленивая инициализация)
        self._wilds_nav = None
        self._resource_manager = None
        self._tiles_nav = None
        self._distributor = None

    # ==================== ЛЕНИВЫЕ СВОЙСТВА ====================

    @property
    def wilds_nav(self) -> WildsNavigation:
        if self._wilds_nav is None:
            self._wilds_nav = WildsNavigation()
        return self._wilds_nav

    @property
    def resource_manager(self) -> WildsResourceManager:
        if self._resource_manager is None:
            self._resource_manager = WildsResourceManager()
        return self._resource_manager

    @property
    def tiles_nav(self) -> TilesNavigation:
        if self._tiles_nav is None:
            self._tiles_nav = TilesNavigation()
        return self._tiles_nav

    @property
    def distributor(self) -> TilesDistributor:
        if self._distributor is None:
            self._distributor = TilesDistributor()
        return self._distributor

    # ==================== can_execute ====================

    def can_execute(self):
        """
        Проверить можно ли отправлять на плитки

        Условия:
        1. Tiles не заморожены
        2. Wilds не заморожены (tiles — расширение wilds)
        3. Не воскресенье
        4. Ещё не отправляли в этой сессии
        5. Автоохота не активна (ждём завершения)
        6. Wilds завершили работу в этой сессии

        Returns:
            True — можно выполнять execute()
            False — пропускаем
        """
        emu_id = self.emulator.get('id')

        # Tiles заморожены?
        if function_freeze_manager.is_frozen(emu_id, self.FUNCTION_NAME):
            return False

        # Wilds заморожены → tiles тоже не работают
        if function_freeze_manager.is_frozen(emu_id, 'wilds'):
            return False

        # Воскресенье — не ходим на плитки
        if datetime.now().weekday() == 6:
            return False

        # Уже отправляли в этой сессии?
        tiles_state = self.session_state.get('tiles', {})
        if tiles_state.get('sent_this_session'):
            return False

        # Автоохота ещё идёт? → ждём
        wilds_state = self.session_state.get('wilds', {})
        if wilds_state.get('hunt_active'):
            return False

        # Wilds должны были отработать в этой сессии
        # (tiles запускаются ТОЛЬКО после успешного завершения wilds)
        if not wilds_state.get('completed_this_session'):
            return False

        return True

    # ==================== execute ====================

    def execute(self):
        """
        Главный метод — полный цикл отправки отрядов на плитки

        Returns:
            True  — ситуация обработана (даже если ничего не отправили)
            False — критическая ошибка навигации → автозаморозка
        """
        emu_id = self.emulator.get('id')

        # 1. Загрузить настройки
        enabled_resources = self._load_enabled_resources(emu_id)
        enabled_squads = self._load_enabled_squads(emu_id)
        min_level, max_level = self._load_level_range(emu_id)

        if not enabled_squads or not enabled_resources:
            logger.info(
                f"[{self.emulator_name}] 🗺 Плитки: нет включённых "
                f"отрядов или ресурсов, пропускаем"
            )
            self._mark_sent()
            return True

        logger.info(
            f"[{self.emulator_name}] 🗺 Плитки: начало "
            f"(отрядов: {len(enabled_squads)}, "
            f"ресурсов: {len(enabled_resources)}, "
            f"ур. {min_level}-{max_level})"
        )

        # 2. Вернуться в поместье для парсинга складов
        if not self.wilds_nav.ensure_in_estate(self.emulator):
            return False

        # 3. Парсинг складов
        storage_data = self.resource_manager._parse_all_storages(
            self.emulator, emu_id, enabled_resources
        )

        # 4. Распределить отряды по ресурсам
        day_of_week = datetime.now().weekday()

        assignments = self.distributor.distribute(
            storage_data=storage_data,
            enabled_squads=enabled_squads,
            enabled_resources=enabled_resources,
            day_of_week=day_of_week,
            emulator_id=emu_id,
        )

        if not assignments:
            logger.info(
                f"[{self.emulator_name}] 🗺 Плитки: нечего отправлять "
                f"(склады полные или нет подходящих ресурсов)"
            )
            self._mark_sent()
            return True

        # Логируем план
        plan_parts = []
        for a in assignments:
            res_name = RESOURCE_NAMES_RU.get(a['resource'], a['resource'])
            squad_name = SQUAD_NAMES_RU.get(a['squad_key'], a['squad_key'])
            plan_parts.append(f"{squad_name}→{res_name}")
        logger.info(
            f"[{self.emulator_name}] 📋 План плиток: [{', '.join(plan_parts)}]"
        )

        # 5. Выйти на карту мира
        if not self.wilds_nav.ensure_on_world_map(self.emulator):
            return False

        # 6. Настроить Лист 2 (если нужно)
        sheet_switched = False
        if self._should_setup_sheet(emu_id):
            if not self.tiles_nav.setup_sheet_2(self.emulator):
                logger.warning(
                    f"[{self.emulator_name}] ⚠️ Не удалось настроить Лист 2, "
                    f"продолжаем на текущем листе"
                )
                # Не замораживаем — пробуем отправить на текущем листе
            else:
                sheet_switched = True

        # 7. Отправить каждый отряд
        sent_count = 0
        for assignment in assignments:
            # Перед каждой отправкой убедиться что мы на карте мира
            if not self.wilds_nav.ensure_on_world_map(self.emulator):
                return False

            success = self.tiles_nav.send_squad_to_tile(
                emulator=self.emulator,
                resource=assignment['resource'],
                level_min=min_level,
                level_max=max_level,
                squad_key=assignment['squad_key'],
            )

            if success:
                sent_count += 1
            else:
                res_name = RESOURCE_NAMES_RU.get(
                    assignment['resource'], assignment['resource']
                )
                squad_name = SQUAD_NAMES_RU.get(
                    assignment['squad_key'], assignment['squad_key']
                )
                logger.warning(
                    f"[{self.emulator_name}] ⚠️ Не удалось отправить "
                    f"{squad_name} на {res_name}"
                )

        logger.info(
            f"[{self.emulator_name}] 🗺 Плитки: отправлено "
            f"{sent_count}/{len(assignments)} отрядов"
        )

        # 8. Обновить трекинг вторника (в session_state для наглядности)
        if day_of_week == 1:  # Tuesday
            visited = self.session_state.setdefault(
                'tiles', {}
            ).setdefault('tuesday_visited', [])
            for a in assignments:
                if a['resource'] not in visited:
                    visited.append(a['resource'])

        # 9. Вернуть Лист 1 (если переключали на Лист 2)
        if sheet_switched:
            logger.info(
                f"[{self.emulator_name}] 📋 Возврат на Лист 1 "
                f"(для следующей автоохоты)"
            )
            if self.wilds_nav.ensure_on_world_map(self.emulator):
                self.wilds_nav.setup_formation_sheet(self.emulator)

        # 10. Пометить как отправленные
        self._mark_sent()

        # 11. Вернуться в поместье
        self.wilds_nav.ensure_in_estate(self.emulator)

        return True

    # ==================== ПЛАНИРОВЩИК ====================

    @staticmethod
    def get_next_event_time(emulator_id):
        """
        Tiles НИКОГДА не влияют на планировщик.
        Они запускаются исключительно в контексте wilds-сессии,
        после успешного завершения автоохоты.
        Время запуска эмулятора определяется только wilds.
        """
        return None

    # ==================== ПРИВАТНЫЕ МЕТОДЫ ====================

    def _mark_sent(self):
        """Пометить что плитки отправлены в этой сессии"""
        self.session_state.setdefault('tiles', {})['sent_this_session'] = True

    def _load_enabled_resources(self, emulator_id: int) -> List[str]:
        """
        Загрузить включённые ресурсы для плиток из gui_config.yaml

        Returns:
            ['apples', 'leaves', 'soil', 'sand'] — только включённые
        """
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(emulator_id)
        settings = emu_settings.get(emu_key, {})
        tiles = settings.get("tiles", {})
        resources = tiles.get("resources", {})

        enabled = []
        for res_key in TILE_RESOURCES:
            if resources.get(res_key, True):  # По умолчанию все включены
                enabled.append(res_key)

        return enabled

    def _load_enabled_squads(self, emulator_id: int) -> List[str]:
        """
        Загрузить включённые отряды из gui_config.yaml (секция squads/вожаки)

        Плитки используют те же отряды что и wilds (секция squads).

        Returns:
            ['special', 'squad_1', ...] — только включённые
        """
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(emulator_id)
        settings = emu_settings.get(emu_key, {})
        squads = settings.get("squads", {})

        enabled = []
        for squad_key in SQUAD_KEYS:
            squad_data = squads.get(squad_key, {})
            if squad_data.get("enabled", False):
                enabled.append(squad_key)

        return enabled

    def _load_level_range(self, emulator_id: int) -> Tuple[int, int]:
        """
        Загрузить диапазон уровней плиток из gui_config.yaml

        Returns:
            (min_level, max_level) — по умолчанию (4, 7)
        """
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(emulator_id)
        settings = emu_settings.get(emu_key, {})
        tiles = settings.get("tiles", {})

        min_level = tiles.get("min_level", 4)
        max_level = tiles.get("max_level", 7)

        # Валидация
        min_level = max(1, min(18, int(min_level)))
        max_level = max(1, min(18, int(max_level)))
        if min_level > max_level:
            min_level = max_level

        return min_level, max_level

    def _should_setup_sheet(self, emulator_id: int) -> bool:
        """
        Нужна ли настройка Листа 2 для плиток

        Условия:
        - В GUI включён "Активировать Лист 2" (use_sheet_2)
        - Лорд ≥ 16 (если есть данные)

        Логика та же что у WildsFunction._should_setup_sheet(),
        только здесь мы переключаем НА Лист 2 (а wilds — на Лист 1).
        """
        gui_config = load_config("configs/gui_config.yaml", silent=True) or {}
        emu_settings = gui_config.get("emulator_settings", {})
        emu_key = str(emulator_id)
        settings = emu_settings.get(emu_key, {})

        wilds = settings.get("wilds", {})
        use_sheet_2 = wilds.get("use_sheet_2", False)

        if not use_sheet_2:
            return False

        # Проверяем уровень Лорда
        try:
            from functions.building.building_database import BuildingDatabase
            building_db = BuildingDatabase()
            lord_level = building_db.get_building_level(emulator_id, "Лорд")
            if lord_level is not None and lord_level < 16:
                return False
        except Exception:
            pass  # Нет данных — на всякий случай настраиваем

        return True