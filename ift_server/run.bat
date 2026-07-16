@echo off
REM Локальный запуск ИФТ-пакета на Windows (для проверки).
REM На боевом Linux-сервере используйте run.sh + Cron.

setlocal
cd /d "%~dp0"

if not exist "logs" mkdir logs
if not exist "downloads" mkdir downloads

if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" "main.py"
) else if exist "..\venv\Scripts\python.exe" (
  "..\venv\Scripts\python.exe" "main.py"
) else (
  python "main.py"
)

exit /b %ERRORLEVEL%
