"""
Ручной поиск моделей rapidocr в .venv

Использование:
    python scripts/manual_find_rapidocr_models.py
"""

from pathlib import Path
import shutil


def manual_find_models():
    print("\n" + "=" * 70)
    print("🔍 РУЧНОЙ ПОИСК МОДЕЛЕЙ RAPIDOCR")
    print("=" * 70 + "\n")

    # Найти .venv (или venv)
    project_root = Path(__file__).parent.parent

    venv_folders = [
        project_root / ".venv",
        project_root / "venv",
        project_root / ".env"
    ]

    site_packages = None

    for venv in venv_folders:
        if venv.exists():
            site_packages_candidate = venv / "Lib" / "site-packages"
            if site_packages_candidate.exists():
                site_packages = site_packages_candidate
                print(f"✅ Найден venv: {venv}")
                print(f"   site-packages: {site_packages}\n")
                break

    if not site_packages:
        print("❌ Не найден venv!")
        print("Попробуйте указать путь вручную.\n")
        return False

    # Поиск rapidocr папок
    print("🔍 Поиск rapidocr папок...\n")

    rapidocr_folders = list(site_packages.glob("rapid*"))

    if not rapidocr_folders:
        print("❌ Не найдены rapidocr папки!")
        print("\nУстановлен ли rapidocr?")
        print("   pip list | findstr rapid\n")
        return False

    print(f"Найдено папок: {len(rapidocr_folders)}\n")

    for folder in rapidocr_folders:
        print(f"📁 {folder.name}")

        # Поиск models внутри
        models_folder = folder / "models"
        if models_folder.exists():
            print(f"   ✅ Есть папка models/")

            # Показать .onnx файлы
            onnx_files = list(models_folder.glob("*.onnx"))
            if onnx_files:
                print(f"   📋 ONNX модели ({len(onnx_files)}):")
                for onnx_file in onnx_files:
                    size_mb = onnx_file.stat().st_size / (1024 * 1024)
                    print(f"      • {onnx_file.name} ({size_mb:.1f} МБ)")

                # Попробуем найти rec модель
                rec_models = [f for f in onnx_files if 'rec' in f.name.lower()]

                if rec_models:
                    print(f"\n   🎯 Найдены REC модели:")
                    for i, rec_model in enumerate(rec_models, 1):
                        print(f"      {i}. {rec_model.name}")

                        # Проверка на cyrillic/russian
                        if any(keyword in rec_model.name.lower() for keyword in ['cyrillic', 'russian', 'ru', 'eslav']):
                            print(f"         ⭐ CYRILLIC МОДЕЛЬ!")

                    # Предложить скопировать
                    print("\n   💡 Хотите скопировать модель?")
                    print(f"      Выберите номер (1-{len(rec_models)}) или Enter для пропуска: ", end='')

                    choice = input().strip()

                    if choice.isdigit() and 1 <= int(choice) <= len(rec_models):
                        selected_model = rec_models[int(choice) - 1]

                        # Скопировать
                        dst_dir = project_root / "data" / "models" / "onnx"
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        dst_file = dst_dir / "rec_model.onnx"

                        # Резервная копия
                        if dst_file.exists():
                            backup = dst_dir / "rec_model_old.onnx"
                            shutil.copy2(dst_file, backup)
                            print(f"\n      💾 Резервная копия: {backup.name}")

                        # Копировать
                        shutil.copy2(selected_model, dst_file)
                        print(f"      ✅ Скопировано: {dst_file}")
                        print(f"\n      🧪 Тестируйте:")
                        print(f"         python tests/test_onnx_raw_output.py\n")

                        return True
            else:
                print(f"   ⚠️ Нет .onnx файлов")
        else:
            print(f"   ⚠️ Нет папки models/")

        print()

    print("=" * 70)
    print("Поиск завершен")
    print("=" * 70 + "\n")

    return False


if __name__ == "__main__":
    try:
        manual_find_models()
    except KeyboardInterrupt:
        print("\n\n⏸️ Прервано")
    except Exception as e:
        print(f"\n\n❌ ОШИБКА: {e}")
        import traceback

        traceback.print_exc()