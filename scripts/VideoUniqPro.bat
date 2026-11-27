@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PATH=%ROOT%vendor\ffmpeg\win64;%ROOT%python;%PATH%"
set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"
set "PYTHONHOME=%ROOT%python"
set "PYTHONUTF8=1"
set "QT_PLUGIN_PATH=%ROOT%python\Lib\site-packages\PySide6\plugins"
set "QT_QPA_PLATFORM_PLUGIN_PATH=%ROOT%python\Lib\site-packages\PySide6\plugins\platforms"

if not exist "%ROOT%python\python.exe" (
  echo [VideoUniq Pro] python.exe not found. Unpack the full portable folder.
  pause
  exit /b 1
)

"%ROOT%python\python.exe" -m videouniq %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo [VideoUniq Pro] exited with code %ERR%
  pause
)
exit /b %ERR%
