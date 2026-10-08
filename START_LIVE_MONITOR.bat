@echo off
setlocal EnableExtensions

rem ===== UTF-8 console =====
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONLEGACYWINDOWSSTDIO=0"

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto RUN_VENV

where py >nul 2>nul
if not errorlevel 1 goto RUN_PY

where python >nul 2>nul
if not errorlevel 1 goto RUN_PYTHON

echo.
echo [ERROR] Python 3 was not found.
echo Install Python 3 or create .venv in this project folder.
echo.
pause
exit /b 1

:RUN_VENV
echo Starting Omsk Live Monitor...
".venv\Scripts\python.exe" -X utf8 "live_monitor.py"
goto FINISH

:RUN_PY
echo Starting Omsk Live Monitor...
py -3 -X utf8 "live_monitor.py"
goto FINISH

:RUN_PYTHON
echo Starting Omsk Live Monitor...
python -X utf8 "live_monitor.py"
goto FINISH

:FINISH
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo [ERROR] Monitor stopped with code %EXIT_CODE%.
if "%EXIT_CODE%"=="0" echo Monitor stopped normally.
echo.
pause
exit /b %EXIT_CODE%
