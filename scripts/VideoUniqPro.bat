@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PATH=%ROOT%vendor\ffmpeg\win64;%ROOT%python;%ROOT%python\Lib\site-packages\PySide6;%ROOT%python\Lib\site-packages\shiboken6;%PATH%"
set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"
set "PYTHONHOME=%ROOT%python"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "QT_PLUGIN_PATH=%ROOT%python\Lib\site-packages\PySide6\plugins"
set "QT_QPA_PLATFORM_PLUGIN_PATH=%ROOT%python\Lib\site-packages\PySide6\plugins\platforms"

if not exist "%ROOT%python\python.exe" (
  echo [VideoUniq Pro] python.exe not found. Unpack the full portable folder.
  pause
  exit /b 1
)
if not exist "%ROOT%boot.py" (
  echo [VideoUniq Pro] boot.py not found. Unpack the full portable folder.
  pause
  exit /b 1
)

"%ROOT%python\python.exe" -u -X utf8 "%ROOT%boot.py" %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo [VideoUniq Pro] exited with code %ERR%
  echo Log: "%ROOT%VideoUniqPro-launch.log"
  echo Log: "%LOCALAPPDATA%\VideoUniqPro\launch.log"
  pause
)
exit /b %ERR%
