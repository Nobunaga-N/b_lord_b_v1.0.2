"""
Поиск рабочей cyrillic rec_model в rapidocr

Использование:
    pip install rapidocr-onnxruntime
    python scripts/find_rapidocr_cyrillic_model.py

Результат:
    - Найдет все модели в rapidocr
    - Скопирует cyrillic rec модель в data/models/onnx/rec_model.onnx
    - Заменит сломанную модель на рабочую
"""

import importlib.util
import shutil
from pathlib import Path


def find_and_copy_cyrillic_model():
    print("\n" + "=" * 70)
    print("🔍 ПОИСК РАБОЧЕЙ CYRILLIC REC_MODEL В RAPIDOCR")
    print("=" * 70 + "\n")

    # 1. Найти rapidocr (проверяем разные варианты импорта)
    rapidocr_module = None

    # Вариант 1: rapidocr_onnxruntime
    try:
        import rapidocr_onnxruntime
        rapidocr_module = rapidocr_onnxruntime
        print("✅ Найден модуль: rapidocr_onnxruntime")
    except ImportError:
        pass

    # Вариант 2: rapidocr
    if rapidocr_module is None:
        try:
            import rapidocr
            rapidocr_module = rapidocr
            print("✅ Найден модуль: rapidocr")
        except ImportError:
            pass

    # Вариант 3: RapidOCR
    if rapidocr_module is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            rapidocr_module = True  # Нашли хоть что-то
            print("✅ Найден класс: RapidOCR")
        except ImportError:
            pass

    if rapidocr_module is None:
        print("❌ rapidocr не найден!")
        print("\nПроверьте установку:")
        print("   pip list | grep rapid")
        print("\nИли попробуйте переустановить:")
        print("   pip uninstall rapidocr-onnxruntime -y")
        print("   pip install rapidocr-onnxruntime\n")
        return False

    # 2. Найти путь к моделям (пробуем разные варианты)
    models_src = None

    # Вариант 1: Через importlib
    for module_name in ['rapidocr_onnxruntime', 'rapidocr']:
        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin:
            rapidocr_path = Path(spec.origin).parent
            models_candidate = rapidocr_path / 'models'

            if models_candidate.exists():
                models_src = models_candidate
                print(f"✅ Найдена папка rapidocr: {models_src}\n")
                break
            else:
                # Попробуем на уровень выше
                models_candidate = rapidocr_path.parent / 'models'
                if models_candidate.exists():
                    models_src = models_candidate
                    print(f"✅ Найдена папка rapidocr: {models_src}\n")
                    break

    if models_src is None:
        print("❌ Папка с моделями не найдена!")
        print("\nПопробуйте найти вручную:")
        print("   1. Найдите папку rapidocr в вашем .venv:")
        print("      .venv/Lib/site-packages/rapidocr*/")
        print("   2. Там должна быть папка models/ с .onnx файлами\n")
        return False

    # 3. Показать все доступные модели
    print("📋 Доступные модели в rapidocr:\n")
    all_models = list(models_src.glob('*.onnx'))

    if not all_models:
        print("⚠️ Нет ONNX моделей в rapidocr!")
        return False

    for model_file in all_models:
        size_mb = model_file.stat().st_size / (1024 * 1024)
        print(f"   • {model_file.name} ({size_mb:.1f} МБ)")

    # 4. Найти cyrillic rec модель
    print("\n🔍 Поиск cyrillic rec модели...\n")

    # Варианты названий
    cyrillic_patterns = [
        'cyrillic*rec*.onnx',
        'russian*rec*.onnx',
        'ru*rec*.onnx',
        'eslav*rec*.onnx',
        '*cyrillic*.onnx'
    ]

    cyrillic_model = None
    for pattern in cyrillic_patterns:
        matches = list(models_src.glob(pattern))
        if matches:
            cyrillic_model = matches[0]
            print(f"✅ Найдена cyrillic модель: {cyrillic_model.name}")
            break

    if not cyrillic_model:
        print("⚠️ Cyrillic модель не найдена в rapidocr!")
        print("\nДоступные rec модели:")
        rec_models = [m for m in all_models if 'rec' in m.name.lower()]
        if rec_models:
            for model in rec_models:
                print(f"   • {model.name}")
            print("\nИспользуем первую rec модель...")
            cyrillic_model = rec_models[0]
        else:
            print("❌ Нет rec моделей в rapidocr!")
            return False

    # 5. Путь назначения
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    dst_dir = project_root / "data" / "models" / "onnx"
    dst_dir.mkdir(parents=True, exist_ok=True)

    dst_file = dst_dir / "rec_model.onnx"

    # 6. Резервная копия старой модели
    if dst_file.exists():
        backup_file = dst_dir / "rec_model_old_BROKEN.onnx"
        print(f"\n💾 Создание резервной копии старой модели...")
        print(f"   {dst_file} → {backup_file}")
        shutil.copy2(dst_file, backup_file)

    # 7. Копирование
    print(f"\n📋 Копирование новой модели:")
    print(f"   {cyrillic_model}")
    print(f"   → {dst_file}")

    shutil.copy2(cyrillic_model, dst_file)

    size_mb = dst_file.stat().st_size / (1024 * 1024)
    print(f"\n✅ Модель скопирована ({size_mb:.1f} МБ)")

    # 8. Словарь символов
    print("\n📝 Проверка словаря символов...")
    dict_file = dst_dir / "ppocr_keys_v1.txt"

    if not dict_file.exists():
        print("⚠️ Словарь не найден, создаем базовый...")

        # Базовый словарь (цифры + латиница + кириллица)
        chars = []
        chars.extend([str(i) for i in range(10)])
        chars.extend([chr(i) for i in range(ord('a'), ord('z') + 1)])
        chars.extend([chr(i) for i in range(ord('A'), ord('Z') + 1)])
        chars.extend([chr(i) for i in range(ord('а'), ord('я') + 1)])
        chars.extend([chr(i) for i in range(ord('А'), ord('Я') + 1)])
        chars.extend(['ё', 'Ё'])
        chars.extend([' ', '.', ',', ':', '-', '(', ')', '/', '\\', 'v', 'V', 'L', 'l'])

        dict_file.write_text('\n'.join(chars), encoding='utf-8')
        print(f"✅ Словарь создан ({len(chars)} символов)")
    else:
        print(f"✅ Словарь существует")

    # 9. Инструкция по тестированию
    print("\n" + "=" * 70)
    print("✅ МОДЕЛЬ ЗАМЕНЕНА!")
    print("=" * 70)

    print("\n🧪 Теперь протестируйте:")
    print("   python tests/test_onnx_raw_output.py")
    print("\nЕсли увидите реальный текст (не '0') - значит модель работает! ✨")
    print("\nЕсли модель НЕ заработала:")
    print("   1. Попробуйте другие rec модели из rapidocr")
    print("   2. Вернитесь к PaddleOCR (он работает хорошо)")
    print("\nРезервная копия старой модели:")
    print(f"   {dst_dir / 'rec_model_old_BROKEN.onnx'}\n")

    return True


if __name__ == "__main__":
    try:
        success = find_and_copy_cyrillic_model()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏸️ Прервано")
        exit(1)
    except Exception as e:
        print(f"\n\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        exit(1)