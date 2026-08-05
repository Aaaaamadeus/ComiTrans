@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python run.py
    ) else (
        py -3 run.py
    )
)

pause
