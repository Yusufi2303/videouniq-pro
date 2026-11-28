# VideoUniq Pro

Пакетная уникализация видео без нейросетей и визуальный редактор (CapCut-стиль). Windows 10/11 x64 (портативная папка с `.exe`) и Linux для разработки.

Стек: Python 3.11+, PySide6, FFmpeg/FFprobe (Qt Multimedia QMediaPlayer, запасные кадры FFmpeg). Версия: **2.1.4**.

## Запуск на Linux (демо / разработка)

```bash
python3 -m pip install -r requirements.txt
PYTHONPATH=src python -m videouniq
```

Нужны `ffmpeg` и `ffprobe` в PATH (на Ubuntu: `sudo apt install ffmpeg`).

## Что умеет V2.1

- Сайдбар: **Видеоредактор**, Уникализатор, История и загрузки, Настройки рендера, Пресеты метаданных, Логи.
- Четыре зоны редактора: медиа+текст, плеер/холст, инспектор, магнитная видеодорожка и несколько текстовых.
- Текст: превью = финал. Слои рисуются Qt в PNG (кастомные шрифты, обводка, тень, скруглённая плашка TikTok) и кладутся через `overlay=enable='between(t,start,end)'`. Сдвиг ±15 px не выходит за safe zone.
- Плеер: автопрокси или HW-decode для роликов тяжелее 1080p; индикатор «Загрузка кадра…» при перемотке.
- GPU: `filter_complex` + `h264_nvenc` / QSV / AMF, принудительный `format=yuv420p` перед энкодером, fallback на `libx264`.
- Кэш: `%LOCALAPPDATA%\VideoUniqPro\cache` (прокси, PNG текста, превью, автосейв). Очистка при выходе (кроме последнего несохранённого `.vup`), мусор старше 24 ч при старте. В настройках: «Размер кэша: N МБ» и «Очистить кэш сейчас».
- Уникализатор: GOP, stereo delay, hue, notch EQ — без ослабления. Один проход FFmpeg: монтаж + уникализация.

## Windows

Распакуйте **всю** папку на рабочий стол и запустите **`VideoUniqPro.exe`** из неё (иконка, без чёрной консоли). Рядом должны остаться `python`, `src`, `vendor`. Не копируйте один `.exe` в другое место. Запасной запуск: `VideoUniqPro.bat`. Внутри уже лежат Python, PySide6 и FFmpeg.

## Сборка Windows zip с Linux

```bash
python3 scripts/build_windows_portable.py
```

Результат: `dist/VideoUniqPro-windows-x64.zip` (внутри `VideoUniqPro.exe`).

На Windows x64 можно собрать один файл PyInstaller:

```bat
pyinstaller --noconfirm videouniq.spec
```

## Тесты ТЗ

```bash
PYTHONPATH=src python3 tests/test_functional.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tests/test_editor.py
PYTHONPATH=src python3 tests/test_v21_battle.py
DISPLAY=:1 PYTHONPATH=src python3 tests/test_live_ui.py
```
