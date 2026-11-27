# VideoUniq Pro

Пакетная уникализация видео без нейросетей. Windows 10/11 x64 (портативная папка) и Linux для разработки.

Стек: Python 3.11+, PySide6, FFmpeg/FFprobe.

## Запуск на Linux (демо / разработка)

```bash
python3 -m pip install -r requirements.txt
PYTHONPATH=src python -m videouniq
```

Нужны `ffmpeg` и `ffprobe` в PATH (на Ubuntu: `sudo apt install ffmpeg`).

## Windows — портативная сборка

Распакуйте zip на рабочий стол и запустите `VideoUniqPro.bat`. Внутри уже лежат Python, PySide6 и FFmpeg. Интернет не нужен.

## Сборка Windows zip с Linux

```bash
python3 scripts/build_windows_portable.py
```

Результат: `dist/VideoUniqPro-windows-x64.zip`.

Позже можно собрать `.exe` через PyInstaller (`videouniq.spec`) на машине с Windows.

## Тесты ТЗ

```bash
PYTHONPATH=src python3 tests/test_functional.py
```
