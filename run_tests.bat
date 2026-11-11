@echo off
chcp 65001 > nul
cd /d "%~dp0"
set "PY_CMD=python"
if exist "venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
)
echo [*] Execution des tests Song-of-my-Ram Studio avec : %PY_CMD%
"%PY_CMD%" -m unittest discover -s tests -v
exit /b %errorlevel%
