"""
Минимальный тест для диагностики PaddleX 3.2.x API

Создаёт простое тестовое изображение с текстом и проверяет структуру результата
"""

import numpy as np
import cv2
from paddlex import create_pipeline

# Создать простое тестовое изображение с текстом
def create_test_image():
    """Создать белое изображение с чёрным текстом"""
    img = np.ones((200, 600, 3), dtype=np.uint8) * 255

    # Добавить текст
    cv2.putText(img, "Logovo Travoyazhnyh Lv.10", (50, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(img, "Logovo Plotoyadnyh Lv.9", (50, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(img, "Logovo Vseyadnyh Lv.5", (50, 150),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    return img

def main():
    print("=" * 60)
    print("🔍 ДИАГНОСТИКА PADDLEX 3.2.x API")
    print("=" * 60)

    # Создать тестовое изображение
    print("\n1️⃣ Создание тестового изображения...")
    test_img = create_test_image()
    print(f"   ✅ Изображение создано: {test_img.shape}")

    # Сохранить для проверки
    cv2.imwrite("test_image.png", test_img)
    print("   💾 Сохранено: test_image.png")

    # Инициализация OCR
    print("\n2️⃣ Инициализация OCR pipeline...")
    pipeline = create_pipeline(pipeline="OCR", device="gpu:0")
    print("   ✅ Pipeline создан")

    # Распознавание
    print("\n3️⃣ Запуск распознавания...")
    result = pipeline.predict(test_img)

    # ДЕТАЛЬНАЯ ДИАГНОСТИКА
    print("\n4️⃣ АНАЛИЗ РЕЗУЛЬТАТА:")
    print(f"   🔍 Type: {type(result)}")
    print(f"   🔍 Is generator: {hasattr(result, '__iter__') and not isinstance(result, (list, dict, str))}")

    # Если генератор - преобразовать в список
    if hasattr(result, '__iter__') and not isinstance(result, (list, dict, str)):
        print("   🔄 Преобразование генератора в список...")
        result = list(result)
        print(f"   ✅ Получено элементов: {len(result)}")

    # Анализ структуры
    if isinstance(result, list):
        print(f"\n5️⃣ СТРУКТУРА СПИСКА:")
        print(f"   📦 Длина: {len(result)}")

        if len(result) > 0:
            first_item = result[0]
            print(f"\n6️⃣ ПЕРВЫЙ ЭЛЕМЕНТ:")
            print(f"   🔍 Type: {type(first_item)}")
            print(f"   🔍 Module: {type(first_item).__module__}")
            print(f"   🔍 Class: {type(first_item).__name__}")

            # Все атрибуты
            print(f"\n7️⃣ АТРИБУТЫ (публичные):")
            public_attrs = [attr for attr in dir(first_item) if not attr.startswith('_')]
            for attr in public_attrs[:10]:  # Первые 10
                print(f"   - {attr}")

            # Если это dict-like объект, показать ключи
            print(f"\n8️⃣ DICT KEYS (если это словарь):")
            if hasattr(first_item, 'keys'):
                try:
                    keys = list(first_item.keys())
                    print(f"   ✅ Это dict-like объект!")
                    print(f"   📦 Ключи: {keys}")

                    # Показать значения всех ключей
                    print(f"\n   📊 ЗНАЧЕНИЯ КЛЮЧЕЙ:")
                    for key in keys:
                        value = first_item[key]
                        print(f"   {key:20} : type={type(value).__name__}")

                        if hasattr(value, '__len__') and not isinstance(value, str):
                            print(f"   {' '*20}   len={len(value)}")

                            if len(value) > 0 and len(value) < 10:
                                print(f"   {' '*20}   data={value}")
                            elif len(value) > 0:
                                print(f"   {' '*20}   first={value[0]}")
                        elif isinstance(value, str):
                            print(f"   {' '*20}   value='{value[:50]}'")
                except Exception as e:
                    print(f"   ❌ Ошибка чтения ключей: {e}")
            else:
                print(f"   ❌ Не dict-like объект")

            # Проверка ключевых атрибутов
            print(f"\n9️⃣ КЛЮЧЕВЫЕ АТРИБУТЫ:")
            for attr in ['dt_polys', 'rec_text', 'rec_score', 'boxes', 'texts', 'scores']:
                has_attr = hasattr(first_item, attr)
                print(f"   {attr:15} : {has_attr}")

                if has_attr:
                    value = getattr(first_item, attr)
                    print(f"      └─ type: {type(value)}")

                    if hasattr(value, '__len__'):
                        print(f"      └─ len: {len(value)}")

                        if len(value) > 0:
                            print(f"      └─ first: {value[0]}")

            # Попробовать to_dict()
            print(f"\n🔟 МЕТОДЫ ИЗВЛЕЧЕНИЯ:")
            if hasattr(first_item, 'to_dict'):
                try:
                    data_dict = first_item.to_dict()
                    print(f"   ✅ to_dict() работает")
                    print(f"      Keys: {list(data_dict.keys())}")
                except Exception as e:
                    print(f"   ❌ to_dict() failed: {e}")
            else:
                print(f"   ❌ to_dict() не найден")

            # Попробовать json()
            if hasattr(first_item, 'json'):
                try:
                    import json
                    json_str = first_item.json()
                    data_dict = json.loads(json_str)
                    print(f"   ✅ json() работает")
                    print(f"      Keys: {list(data_dict.keys())}")

                    # Показать полное содержимое JSON (первые 1000 символов)
                    print(f"\n1️⃣1️⃣ JSON СОДЕРЖИМОЕ (первые 1000 символов):")
                    print(f"   {json_str[:1000]}")
                except Exception as e:
                    print(f"   ❌ json() failed: {e}")
            else:
                print(f"   ❌ json() не найден")

            # Попробовать __dict__
            if hasattr(first_item, '__dict__'):
                print(f"\n   📦 __dict__ keys: {list(first_item.__dict__.keys())}")

    print("\n" + "=" * 60)
    print("✅ ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 60)

if __name__ == "__main__":
    main()