"""
Движок распознавания текста через ONNX Runtime

Использует готовые ONNX модели от PaddleOCR:
- Detection model (детекция текстовых регионов)
- Recognition model (распознавание текста)
- Classification model (определение ориентации)

Преимущества ONNX Runtime:
- Универсальная поддержка GPU (NVIDIA CUDA, AMD/Intel DirectML)
- На 30% быстрее CPU версии PaddleOCR
- Меньший размер моделей (~20 МБ vs 200-500 МБ)
- Критично для 8-10 одновременных эмуляторов
"""

import os
import re
import cv2
import numpy as np
from datetime import datetime
from utils.logger import logger


class OCREngineONNX:
    """
    Движок распознавания текста через ONNX Runtime

    Возможности:
    - Распознавание русского и английского текста
    - Построчная группировка элементов
    - Парсинг уровней зданий (Lv.X)
    - Парсинг таймеров (HH:MM:SS)
    - Парсинг названий зданий
    - Debug режим (сохранение изображений с bbox)

    Singleton: используйте get_ocr_engine_onnx() для получения экземпляра
    """

    def __init__(self, model_dir=None):
        """
        Инициализация ONNX Runtime OCR

        Args:
            model_dir: папка с .onnx моделями (по умолчанию: data/models/onnx в корне проекта)
        """
        try:
            import onnxruntime as ort
            from pathlib import Path

            # ИСПРАВЛЕНИЕ: Определить корень проекта относительно текущего файла
            if model_dir is None:
                # Текущий файл: utils/ocr_engine_onnx.py
                # Корень проекта: на 1 уровень выше
                current_file = Path(__file__)
                project_root = current_file.parent.parent
                model_dir = project_root / "data" / "models" / "onnx"

            # Конвертировать в строку
            self.model_dir = str(model_dir)
            self.debug_mode = False

            logger.debug(f"Путь к моделям ONNX: {self.model_dir}")

            # 1. Определить доступные провайдеры
            self.providers = self._detect_providers(ort)

            # 2. Загрузить 3 модели
            self.det_session = self._load_model(ort, 'det_model.onnx')
            self.rec_session = self._load_model(ort, 'rec_model.onnx')
            self.cls_session = self._load_model(ort, 'cls_model.onnx')

            # 3. Загрузить словарь символов
            self.char_dict = self._load_char_dict()

            logger.success(f"OCREngineONNX готов (провайдер: {self.providers[0]})")

        except Exception as e:
            logger.error(f"Ошибка инициализации ONNX Runtime OCR: {e}")
            raise

    def _detect_providers(self, ort):
        """
        Автоопределение лучшего провайдера

        Приоритет:
        1. CUDAExecutionProvider (NVIDIA GPU)
        2. DmlExecutionProvider (AMD/Intel GPU)
        3. CPUExecutionProvider (Fallback)

        Args:
            ort: модуль onnxruntime

        Returns:
            list: ['CUDAExecutionProvider', 'CPUExecutionProvider']
        """
        available = ort.get_available_providers()
        logger.debug(f"Доступные провайдеры ONNX: {available}")

        # Порядок приоритета
        priority = [
            'CUDAExecutionProvider',  # NVIDIA
            'DmlExecutionProvider',  # DirectML (AMD/Intel)
            'CPUExecutionProvider'  # CPU (всегда есть)
        ]

        # Выбрать лучший доступный
        providers = [p for p in priority if p in available]

        if 'CUDAExecutionProvider' in providers:
            logger.success("✓ Используется NVIDIA GPU (CUDA)")
        elif 'DmlExecutionProvider' in providers:
            logger.success("✓ Используется DirectML GPU (AMD/Intel)")
        else:
            logger.info("✓ Используется CPU")

        return providers

    def _load_model(self, ort, model_name):
        """
        Загружает ONNX модель

        Args:
            ort: модуль onnxruntime
            model_name: имя файла модели

        Returns:
            InferenceSession: сессия ONNX
        """
        model_path = os.path.join(self.model_dir, model_name)

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Модель не найдена: {model_path}\n"
                f"Запустите: python scripts/download_onnx_models.py"
            )

        # Опции сессии (для оптимизации)
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        # Создать сессию
        session = ort.InferenceSession(
            model_path,
            sess_options=sess_options,
            providers=self.providers
        )

        logger.debug(f"ONNX модель загружена: {model_name}")
        return session

    def _load_char_dict(self):
        """
        Загружает словарь символов для recognition модели

        Returns:
            dict: {индекс: символ}
        """
        dict_path = os.path.join(self.model_dir, 'ppocr_keys_v1.txt')

        if not os.path.exists(dict_path):
            logger.warning(f"Словарь не найден: {dict_path}")
            logger.warning("Используется базовый словарь (цифры + латиница + кириллица)")

            # Базовый словарь
            chars = []
            chars.extend([str(i) for i in range(10)])  # 0-9
            chars.extend([chr(i) for i in range(ord('a'), ord('z') + 1)])  # a-z
            chars.extend([chr(i) for i in range(ord('A'), ord('Z') + 1)])  # A-Z
            chars.extend([chr(i) for i in range(ord('а'), ord('я') + 1)])  # а-я
            chars.extend([chr(i) for i in range(ord('А'), ord('Я') + 1)])  # А-Я
            chars.extend(['ё', 'Ё'])
            chars.extend([' ', '.', ',', ':', '-', '(', ')', '/', '\\'])
        else:
            # Загрузить из файла
            with open(dict_path, 'r', encoding='utf-8') as f:
                chars = [line.strip() for line in f.readlines()]

        # Создать словарь: индекс → символ
        char_dict = {i: char for i, char in enumerate(chars)}
        char_dict[len(chars)] = ' '  # Пробел для blank в CTC

        logger.debug(f"Словарь символов загружен: {len(chars)} символов")
        return char_dict

    def set_debug_mode(self, enabled):
        """
        Включает/выключает debug режим

        Args:
            enabled: True для включения, False для выключения
        """
        self.debug_mode = enabled
        logger.info(f"OCR debug режим: {'ВКЛ' if enabled else 'ВЫКЛ'}")

    def recognize_text(self, image, region=None, min_confidence=0.5):
        """
        Распознает текст на изображении

        Алгоритм:
        1. Детекция текстовых регионов (det_model)
        2. Классификация ориентации (cls_model)
        3. Распознавание текста (rec_model)

        Args:
            image: numpy.ndarray (BGR формат OpenCV)
            region: tuple (x1, y1, x2, y2) - область для OCR (опционально)
            min_confidence: минимальный порог уверенности (0.0-1.0)

        Returns:
            list: Список распознанных элементов
            [
                {
                    'text': 'Ферма Грунта',
                    'confidence': 0.98,
                    'bbox': [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
                    'x': 120,  # Центр по X
                    'y': 582   # Центр по Y
                },
                ...
            ]
        """
        try:
            # Обрезать регион если указан
            if region:
                x1, y1, x2, y2 = region
                image = image[y1:y2, x1:x2].copy()

            # 1. Детекция текстовых регионов
            boxes = self._detect_text_regions(image)

            if not boxes or len(boxes) == 0:
                logger.debug("OCR не обнаружил текстовые регионы")
                return []

            logger.debug(f"OCR обнаружил {len(boxes)} текстовых регионов")

            # 2. Для каждого региона
            elements = []
            for box in boxes:
                # Вырезать регион
                region_img = self._crop_region(image, box)

                if region_img is None or region_img.size == 0:
                    continue

                # Классификация ориентации (нужно ли поворачивать)
                angle = self._classify_orientation(region_img)
                if angle == 180:
                    region_img = cv2.rotate(region_img, cv2.ROTATE_180)

                # Распознавание текста
                text, conf = self._recognize_region(region_img)

                # Фильтр по confidence
                if conf < min_confidence:
                    continue

                # Вычислить центр bbox
                x_center = int((box[0][0] + box[2][0]) / 2)
                y_center = int((box[0][1] + box[2][1]) / 2)

                # Добавить смещение если был region
                if region:
                    x_center += region[0]
                    y_center += region[1]
                    box = [[p[0] + region[0], p[1] + region[1]] for p in box]

                elements.append({
                    'text': text.strip(),
                    'confidence': float(conf),
                    'bbox': box,
                    'x': x_center,
                    'y': y_center
                })

            logger.debug(f"OCR распознал {len(elements)} элементов (порог: {min_confidence})")
            return elements

        except Exception as e:
            logger.error(f"Ошибка OCR распознавания: {e}")
            logger.exception(e)
            return []

    def _detect_text_regions(self, image):
        """
        Детекция текстовых регионов (det_model)

        Args:
            image: numpy.ndarray (BGR)

        Returns:
            list: Список bbox [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        """
        # Препроцессинг для детекции
        img_resized, ratio_h, ratio_w = self._preprocess_det(image)

        # Inference
        input_name = self.det_session.get_inputs()[0].name
        output_name = self.det_session.get_outputs()[0].name

        outputs = self.det_session.run(
            [output_name],
            {input_name: img_resized}
        )

        # Постпроцессинг
        boxes = self._postprocess_det(outputs[0], ratio_h, ratio_w, image.shape)

        return boxes

    def _preprocess_det(self, image):
        """
        Препроцессинг для detection модели

        Args:
            image: numpy.ndarray (BGR)

        Returns:
            tuple: (preprocessed_image, ratio_h, ratio_w)
        """
        # Конвертировать BGR → RGB
        img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Целевой размер (макс сторона = 960, кратно 32)
        h, w = img.shape[:2]
        max_side = 960

        if max(h, w) > max_side:
            if h > w:
                new_h = max_side
                new_w = int(w * (max_side / h))
            else:
                new_w = max_side
                new_h = int(h * (max_side / w))
        else:
            new_h, new_w = h, w

        # Округлить до кратности 32
        new_h = (new_h // 32) * 32
        new_w = (new_w // 32) * 32

        # Resize
        img_resized = cv2.resize(img, (new_w, new_h))

        # Нормализация
        img_normalized = img_resized.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406]).reshape(1, 1, 3)
        std = np.array([0.229, 0.224, 0.225]).reshape(1, 1, 3)
        img_normalized = (img_normalized - mean) / std

        # Transpose (H, W, C) → (C, H, W)
        img_transposed = img_normalized.transpose(2, 0, 1)

        # Добавить batch dimension
        img_batch = np.expand_dims(img_transposed, axis=0).astype(np.float32)

        # Коэффициенты масштабирования
        ratio_h = new_h / h
        ratio_w = new_w / w

        return img_batch, ratio_h, ratio_w

    def _postprocess_det(self, pred, ratio_h, ratio_w, original_shape):
        """
        Постпроцессинг для detection модели (DBNet)

        Args:
            pred: выход модели (batch, 1, H, W)
            ratio_h: коэффициент высоты
            ratio_w: коэффициент ширины
            original_shape: исходный размер изображения

        Returns:
            list: Список bbox [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        """
        # Извлечь probability map
        pred_map = pred[0, 0, :, :]  # (H, W)

        # Бинаризация (порог 0.3)
        mask = pred_map > 0.3
        mask = mask.astype(np.uint8) * 255

        # Найти контуры
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        boxes = []
        for contour in contours:
            # Минимальная площадь
            if cv2.contourArea(contour) < 10:
                continue

            # Минимальный прямоугольник
            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect)

            # Масштабирование обратно к исходному размеру
            box[:, 0] = box[:, 0] / ratio_w
            box[:, 1] = box[:, 1] / ratio_h

            # Clip к границам изображения
            box[:, 0] = np.clip(box[:, 0], 0, original_shape[1])
            box[:, 1] = np.clip(box[:, 1], 0, original_shape[0])

            # Конвертировать в список
            box = box.astype(np.int32).tolist()
            boxes.append(box)

        return boxes

    def _classify_orientation(self, image):
        """
        Классификация ориентации текста (cls_model)

        Args:
            image: numpy.ndarray (BGR)

        Returns:
            int: угол (0 или 180)
        """
        # Препроцессинг для классификации
        img_preprocessed = self._preprocess_cls(image)

        # Inference
        input_name = self.cls_session.get_inputs()[0].name
        output_name = self.cls_session.get_outputs()[0].name

        outputs = self.cls_session.run(
            [output_name],
            {input_name: img_preprocessed}
        )

        # Постпроцессинг
        prob = outputs[0][0]  # [prob_0, prob_180]
        angle = 0 if prob[0] > prob[1] else 180

        return angle

    def _preprocess_cls(self, image):
        """
        Препроцессинг для classification модели

        Args:
            image: numpy.ndarray (BGR)

        Returns:
            numpy.ndarray: preprocessed image (1, 3, 48, 192)
        """
        # Конвертировать BGR → RGB
        img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Resize до фиксированного размера 192x48
        img_resized = cv2.resize(img, (192, 48))

        # Нормализация
        img_normalized = img_resized.astype(np.float32) / 255.0
        mean = np.array([0.5, 0.5, 0.5]).reshape(1, 1, 3)
        std = np.array([0.5, 0.5, 0.5]).reshape(1, 1, 3)
        img_normalized = (img_normalized - mean) / std

        # Transpose (H, W, C) → (C, H, W)
        img_transposed = img_normalized.transpose(2, 0, 1)

        # Добавить batch dimension
        img_batch = np.expand_dims(img_transposed, axis=0).astype(np.float32)

        return img_batch

    def _recognize_region(self, image):
        """
        Распознавание текста в регионе (rec_model)

        Args:
            image: numpy.ndarray (BGR)

        Returns:
            tuple: (text, confidence)
        """
        # Препроцессинг для recognition
        img_preprocessed = self._preprocess_rec(image)

        # Inference
        input_name = self.rec_session.get_inputs()[0].name
        output_name = self.rec_session.get_outputs()[0].name

        outputs = self.rec_session.run(
            [output_name],
            {input_name: img_preprocessed}
        )

        # Постпроцессинг (CTC decode)
        text, conf = self._postprocess_rec(outputs[0])

        return text, conf

    def _preprocess_rec(self, image):
        """
        Препроцессинг для recognition модели

        Args:
            image: numpy.ndarray (BGR)

        Returns:
            numpy.ndarray: preprocessed image (1, 3, 48, W)
        """
        # Конвертировать BGR → RGB
        img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Фиксированная высота 48, ширина пропорциональна
        h, w = img.shape[:2]
        target_h = 48
        target_w = int(w * (target_h / h))

        # Ограничение по ширине (макс 320)
        if target_w > 320:
            target_w = 320

        # Resize
        img_resized = cv2.resize(img, (target_w, target_h))

        # Нормализация
        img_normalized = img_resized.astype(np.float32) / 255.0
        mean = np.array([0.5, 0.5, 0.5]).reshape(1, 1, 3)
        std = np.array([0.5, 0.5, 0.5]).reshape(1, 1, 3)
        img_normalized = (img_normalized - mean) / std

        # Transpose (H, W, C) → (C, H, W)
        img_transposed = img_normalized.transpose(2, 0, 1)

        # Добавить batch dimension
        img_batch = np.expand_dims(img_transposed, axis=0).astype(np.float32)

        return img_batch

    def _postprocess_rec(self, pred):
        """
        Постпроцессинг для recognition модели (CTC decode)

        Args:
            pred: выход модели (batch, time_steps, num_classes)

        Returns:
            tuple: (text, confidence)
        """
        # CTC greedy decode
        pred_indices = pred[0].argmax(axis=1)  # (time_steps,)

        # Удалить повторяющиеся символы и blank
        chars = []
        confidences = []
        prev_idx = -1

        for idx in pred_indices:
            if idx != prev_idx and idx < len(self.char_dict):
                char = self.char_dict.get(idx, '')
                if char and char != ' ':  # Пропускаем blank
                    chars.append(char)
                    confidences.append(pred[0, :, idx].max())
            prev_idx = idx

        text = ''.join(chars)
        conf = np.mean(confidences) if confidences else 0.0

        return text, conf

    def _crop_region(self, image, box):
        """
        Вырезает регион из изображения по bbox

        Args:
            image: numpy.ndarray (BGR)
            box: bbox [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]

        Returns:
            numpy.ndarray: вырезанный регион
        """
        # Конвертировать в numpy array
        box = np.array(box, dtype=np.float32)

        # Получить минимальный прямоугольник
        rect = cv2.minAreaRect(box)
        box_points = cv2.boxPoints(rect).astype(np.int32)

        # Вычислить размеры
        width = int(rect[1][0])
        height = int(rect[1][1])

        if width <= 0 or height <= 0:
            return None

        # Целевые координаты (прямоугольник)
        dst_points = np.array([
            [0, 0],
            [width - 1, 0],
            [width - 1, height - 1],
            [0, height - 1]
        ], dtype=np.float32)

        # Матрица трансформации
        M = cv2.getPerspectiveTransform(box, dst_points)

        # Выровнять регион
        warped = cv2.warpPerspective(image, M, (width, height))

        return warped

    # ===== МЕТОДЫ ПАРСИНГА (БЕЗ ИЗМЕНЕНИЙ ИЗ ТЕКУЩЕЙ ВЕРСИИ) =====

    def group_by_rows(self, elements, y_threshold=20):
        """
        Группирует элементы по строкам на основе Y-координат

        Args:
            elements: список элементов из recognize_text()
            y_threshold: максимальная разница по Y для одной строки (пикселей)

        Returns:
            list: Список строк
        """
        if not elements:
            return []

        # Сортировка по Y (сверху вниз)
        sorted_elements = sorted(elements, key=lambda e: e['y'])

        rows = []
        current_row = [sorted_elements[0]]
        current_y = sorted_elements[0]['y']

        # Группировка
        for element in sorted_elements[1:]:
            if abs(element['y'] - current_y) <= y_threshold:
                current_row.append(element)
            else:
                current_row.sort(key=lambda e: e['x'])
                rows.append(current_row)
                current_row = [element]
                current_y = element['y']

        # Добавить последнюю строку
        if current_row:
            current_row.sort(key=lambda e: e['x'])
            rows.append(current_row)

        logger.debug(f"Элементы сгруппированы в {len(rows)} строк (threshold: {y_threshold}px)")
        return rows

    def parse_level(self, text):
        """
        Извлекает уровень из текста 'Lv.X'

        Args:
            text: строка для парсинга

        Returns:
            int или None
        """
        pattern = r'L\s*v\s*\.\s*(\d+)'
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            level = int(match.group(1))
            logger.debug(f"Распознан уровень: {level} из '{text}'")
            return level

        return None

    def parse_timer(self, text):
        """
        Парсит таймер HH:MM:SS и конвертирует в секунды

        Args:
            text: строка с таймером

        Returns:
            int (секунды) или None
        """
        pattern = r'(\d{1,2}):(\d{2}):(\d{2})'
        match = re.search(pattern, text)

        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = int(match.group(3))

            if minutes > 59 or seconds > 59:
                logger.warning(f"Некорректный таймер: {text}")
                return None

            total_seconds = hours * 3600 + minutes * 60 + seconds
            logger.debug(f"Распознан таймер: {text} = {total_seconds} секунд")
            return total_seconds

        return None

    def parse_building_name(self, text):
        """
        Очищает название здания от 'Lv.X', 'Перейти' и лишнего текста

        Args:
            text: строка для очистки

        Returns:
            str: очищенное название
        """
        text = re.sub(r'\s+L\s*v\s*\.\s*\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*Перейти\s*', '', text, flags=re.IGNORECASE)
        text = text.replace('\n', ' ')
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        return text

    def parse_navigation_panel(self, screenshot, emulator_id=None):
        """
        Парсит панель навигации с привязкой название ↔ уровень ↔ индекс

        Args:
            screenshot: numpy.ndarray (BGR формат)
            emulator_id: int (для debug, опционально)

        Returns:
            list: Список зданий
        """
        logger.info("Парсинг панели навигации...")

        # 1. OCR распознавание
        elements = self.recognize_text(screenshot, min_confidence=0.5)

        # Debug режим
        if self.debug_mode and emulator_id is not None:
            self._save_debug_image(screenshot, elements, emulator_id, "navigation")

        if not elements:
            logger.warning("OCR не распознал элементы на панели навигации")
            return []

        # 2. Группировка по строкам
        rows = self.group_by_rows(elements, y_threshold=20)

        # 3. Парсинг каждой строки
        buildings = []
        building_counters = {}

        for row in rows:
            full_text = ' '.join([elem['text'] for elem in row])

            level = self.parse_level(full_text)
            building_name = self.parse_building_name(full_text)

            if not building_name or level is None:
                continue

            if len(building_name) < 3:
                continue

            y_coord = int(sum([elem['y'] for elem in row]) / len(row))

            if building_name not in building_counters:
                building_counters[building_name] = 0
            building_counters[building_name] += 1

            index = building_counters[building_name]
            button_coord = (330, y_coord)

            buildings.append({
                'name': building_name,
                'level': level,
                'index': index,
                'y_coord': y_coord,
                'button_coord': button_coord
            })

        logger.success(f"Распознано {len(buildings)} зданий в панели навигации")
        return buildings

    def _save_debug_image(self, image, elements, emulator_id, operation):
        """
        Сохраняет debug скриншот с bbox и текстом

        Args:
            image: numpy.ndarray (оригинальное изображение)
            elements: список элементов из recognize_text()
            emulator_id: int (ID эмулятора)
            operation: str (тип операции)
        """
        try:
            debug_folder = "data/screenshots/debug/ocr"
            os.makedirs(debug_folder, exist_ok=True)

            debug_img = image.copy()

            if not elements:
                cv2.putText(debug_img, "NO TEXT DETECTED BY OCR", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                logger.warning("OCR debug: текст не распознан на изображении")
            else:
                for elem in elements:
                    bbox = elem['bbox']
                    text = elem['text']
                    confidence = elem['confidence']

                    if confidence >= 0.9:
                        color = (0, 255, 0)
                    elif confidence >= 0.7:
                        color = (0, 255, 255)
                    else:
                        color = (0, 0, 255)

                    points = np.array(bbox, dtype=np.int32)
                    cv2.polylines(debug_img, [points], True, color, 2)

                    x = int(bbox[0][0])
                    y = int(bbox[0][1]) - 5
                    label = f"{text} ({confidence:.2f})"

                    text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                    cv2.rectangle(debug_img,
                                  (x, y - text_size[1] - 5),
                                  (x + text_size[0], y),
                                  (0, 0, 0),
                                  -1)

                    cv2.putText(debug_img, label, (x, y - 2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"emu{emulator_id}_{operation}_{timestamp}.png"
            filepath = os.path.join(debug_folder, filename)

            cv2.imwrite(filepath, debug_img)

            abs_path = os.path.abspath(filepath)
            logger.info(f"OCR debug скриншот сохранен: {abs_path}")
            print(f"   📁 {abs_path}")

        except Exception as e:
            logger.error(f"Ошибка сохранения OCR debug скриншота: {e}")


# ============================================
# Singleton
# ============================================

_ocr_onnx_instance = None


def get_ocr_engine_onnx():
    """
    Возвращает единственный экземпляр OCREngineONNX (Singleton)

    Returns:
        OCREngineONNX: глобальный экземпляр
    """
    global _ocr_onnx_instance

    if _ocr_onnx_instance is None:
        logger.info("Создание OCREngineONNX (Singleton)...")
        _ocr_onnx_instance = OCREngineONNX()
        logger.success("OCREngineONNX готов к использованию")

    return _ocr_onnx_instance