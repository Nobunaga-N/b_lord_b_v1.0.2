"""
Экспорт ONNX моделей из существующего кеша PaddleX

Использование:
    python scripts/download_onnx_models.py

Результат:
    data/models/onnx/
        ├── det_model.onnx          (~8 МБ)
        ├── rec_model.onnx          (~10 МБ)
        ├── cls_model.onnx          (~2 МБ)
        └── ppocr_keys_v1.txt       (словарь символов)

Источник: Экспорт из кеша PaddleX (~/.paddlex/official_models/)
"""

import os
import sys
import shutil
from pathlib import Path


def download_file(url, save_path):
    """
    Скачивает файл с индикатором прогресса

    Args:
        url: URL файла
        save_path: путь для сохранения
    """
    import urllib.request

    print(f"   📥 Скачивание...")

    def progress_hook(count, block_size, total_size):
        if total_size > 0:
            percent = int(count * block_size * 100 / total_size)
            sys.stdout.write(f"\r      Прогресс: {percent}% ")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, save_path, progress_hook)
    print()  # Новая строка после прогресса


def copy_from_rapidocr():
    """
    Копирует ONNX модели из библиотеки rapidocr_onnxruntime

    Returns:
        bool: успех копирования
    """
    try:
        import rapidocr_onnxruntime
        import importlib.util

        # Найти путь к установленной библиотеке
        spec = importlib.util.find_spec('rapidocr_onnxruntime')
        if not spec or not spec.origin:
            return False

        rapidocr_path = Path(spec.origin).parent
        models_src = rapidocr_path / 'models'

        if not models_src.exists():
            return False

        # Путь к папке моделей (относительно КОРНЯ проекта)
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
        models_dst = project_root / "data" / "models" / "onnx"
        models_dst.mkdir(parents=True, exist_ok=True)

        print(f"✅ Найдена библиотека rapidocr_onnxruntime")
        print(f"   Источник: {models_src}")
        print(f"   Назначение: {models_dst}\n")

        # Показать все доступные модели
        print("📋 Доступные модели в библиотеке:")
        available_models = list(models_src.glob('*.onnx'))
        for model_file in available_models:
            size_mb = model_file.stat().st_size / (1024 * 1024)
            print(f"   • {model_file.name} ({size_mb:.1f} МБ)")
        print()

        # Маппинг для копирования (с вариантами названий)
        models_to_copy = {
            'det_model.onnx': [
                'ch_PP-OCRv4_det_infer.onnx',
                'ch_PP-OCRv3_det_infer.onnx',
                'en_PP-OCRv3_det_infer.onnx'
            ],
            'rec_model.onnx': [
                'cyrillic_PP-OCRv4_rec_infer.onnx',
                'en_PP-OCRv4_rec_infer.onnx',
                'ch_PP-OCRv4_rec_infer.onnx',
                'ch_PP-OCRv3_rec_infer.onnx'
            ],
            'cls_model.onnx': [
                'ch_ppocr_mobile_v2.0_cls_infer.onnx'
            ]
        }

        copied = 0
        missing = []

        for dst_name, src_variants in models_to_copy.items():
            dst_file = models_dst / dst_name

            # Проверить существование
            if dst_file.exists():
                print(f"✅ {dst_name} уже существует (пропускаю)")
                copied += 1
                continue

            # Попробовать найти файл из списка вариантов
            src_file = None
            for variant in src_variants:
                candidate = models_src / variant
                if candidate.exists():
                    src_file = candidate
                    break

            # Если не нашли по точному имени - попробовать по паттерну
            if not src_file:
                # Извлечь ключевые слова из первого варианта
                keywords = src_variants[0].replace('_infer.onnx', '').split('_')

                for model_file in available_models:
                    # Проверить совпадение ключевых слов
                    model_lower = model_file.name.lower()
                    if any(kw.lower() in model_lower for kw in keywords if len(kw) > 2):
                        src_file = model_file
                        break

            if not src_file:
                print(f"⚠️  {dst_name} - не найден источник в библиотеке")
                missing.append(dst_name)
                continue

            print(f"📋 Копирование: {src_file.name} → {dst_name}")
            shutil.copy2(src_file, dst_file)

            size_mb = dst_file.stat().st_size / (1024 * 1024)
            print(f"   ✅ Скопировано ({size_mb:.1f} МБ)\n")
            copied += 1

        if missing:
            print(f"\n⚠️  Не удалось скопировать: {', '.join(missing)}")
            return False

        return copied >= len(models_to_copy)

    except ImportError:
        return False
    except Exception as e:
        print(f"⚠️  Ошибка копирования: {e}")
        import traceback
        traceback.print_exc()
        return False


def convert_to_onnx():
    """
    Получает ONNX модели используя rapidocr_onnxruntime
    или показывает инструкцию для ручной загрузки
    """
    print("\n" + "="*70)
    print("🚀 ПОЛУЧЕНИЕ ONNX МОДЕЛЕЙ")
    print("="*70 + "\n")

    # ВАЖНО: Создать папку относительно КОРНЯ проекта, а не scripts/
    # Получить путь к корню проекта (на уровень выше scripts/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    models_dir = project_root / "data" / "models" / "onnx"
    models_dir.mkdir(parents=True, exist_ok=True)

    # СПОСОБ 1: Попробовать скопировать из rapidocr_onnxruntime
    print("📦 СПОСОБ 1: Копирование из rapidocr_onnxruntime\n")

    if copy_from_rapidocr():
        print("\n✅ Модели успешно скопированы из rapidocr_onnxruntime!")
    else:
        print("⚠️  rapidocr_onnxruntime не установлен или модели не найдены\n")

        # СПОСОБ 2: Инструкция для ручной установки
        print("="*70)
        print("📝 СПОСОБ 2: Установка rapidocr_onnxruntime (РЕКОМЕНДУЕТСЯ)")
        print("="*70 + "\n")

        print("Установите библиотеку с готовыми ONNX моделями:")
        print("   pip install rapidocr-onnxruntime\n")

        print("После установки запустите этот скрипт снова.")
        print("Модели будут автоматически скопированы.\n")

        print("="*70)
        print("📝 СПОСОБ 3: Ручная загрузка (если способ 2 не работает)")
        print("="*70 + "\n")

        print("Скачайте модели вручную по прямым ссылкам:\n")

        # Прямые ссылки на рабочие модели
        manual_links = {
            'det_model.onnx': 'https://huggingface.co/spaces/PaddlePaddle/PaddleOCR/resolve/main/inference/det_mv3_db_v2.0.onnx',
            'rec_model.onnx': 'https://huggingface.co/spaces/PaddlePaddle/PaddleOCR/resolve/main/inference/rec_crnn_ru.onnx',
            'cls_model.onnx': 'https://huggingface.co/spaces/PaddlePaddle/PaddleOCR/resolve/main/inference/cls_mv3.onnx'
        }

        print("1. Перейдите по ссылкам и скачайте файлы:")
        for filename, url in manual_links.items():
            print(f"\n   {filename}:")
            print(f"   {url}")

        print(f"\n2. Сохраните файлы в папку:\n   {models_dir.absolute()}\n")

        print("3. Запустите скрипт снова для проверки\n")

        return False

    # Проверить все ли модели на месте
    required_files = ['det_model.onnx', 'rec_model.onnx', 'cls_model.onnx']
    missing = [f for f in required_files if not (models_dir / f).exists()]

    if missing:
        print(f"\n⚠️  Отсутствуют модели: {', '.join(missing)}")
        return False

    # Создать словарь символов
    dict_path = models_dir / 'ppocr_keys_v1.txt'

    if not dict_path.exists():
        print("\n📥 Создание словаря символов...")

        # Базовый словарь
        chars = []
        chars.extend([str(i) for i in range(10)])
        chars.extend([chr(i) for i in range(ord('a'), ord('z')+1)])
        chars.extend([chr(i) for i in range(ord('A'), ord('Z')+1)])
        chars.extend([chr(i) for i in range(ord('а'), ord('я')+1)])
        chars.extend([chr(i) for i in range(ord('А'), ord('Я')+1)])
        chars.extend(['ё', 'Ё'])
        chars.extend([' ', '.', ',', ':', '-', '(', ')', '/', '\\', 'v', 'V', 'L', 'l'])

        dict_path.write_text('\n'.join(chars), encoding='utf-8')
        print(f"   ✅ Словарь создан ({len(chars)} символов)\n")

    print("\n" + "="*70)
    print("✅ ВСЕ МОДЕЛИ ГОТОВЫ!")
    print("="*70 + "\n")

    print(f"📁 Модели сохранены в: {models_dir.absolute()}\n")
    print("Содержимое:")
    for file in sorted(models_dir.iterdir()):
        if file.is_file():
            size_mb = file.stat().st_size / (1024 * 1024)
            print(f"   • {file.name} ({size_mb:.1f} МБ)")

    print("\n🚀 Теперь можно тестировать OCREngine на ONNX Runtime!")
    print("   Запустите: python tests/test_ocr_onnx.py\n")

    return True


if __name__ == "__main__":
    try:
        success = convert_to_onnx()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏸️  Скачивание прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)