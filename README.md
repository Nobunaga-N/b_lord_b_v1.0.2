# B Lord Bot v3.0

Автоматизированный бот для игры Beast Lord: The New Land

## Установка

1. Установить зависимости:
```bash
pip install -r requirements.txt
```

2. Запустить GUI:
```bash
python main_gui.py
```

## Требования

- Windows OS
- LDPlayer 9
- Python 3.8+

## Текущий этап разработки

**ЭТАП 0** - Базовый функционал (MVP)

______
#  Настройка работы с OCR
-  Удалить другие версии OCR (pip uninstall paddlepaddle-gpu -y)
-  Установить версию для CUDA 12.0 со всеми зависимостями - Нужно для работы OCR.
pip install paddlepaddle-gpu==2.6.1.post120 -f https://www.paddlepaddle.org.cn/whl/windows/mkl/avx/stable.html
- Установить ToolKit12 - https://clck.ru/3PiiVj
- Download cuDNN v8.9.7 (December 5th, 2023), for CUDA 12.x2 - https://developer.nvidia.com/rdp/cudnn-archive (скопирывать все файлы из папок bin, include, lib в тулкит в соответствубщие папки)

