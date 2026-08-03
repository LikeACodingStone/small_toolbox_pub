@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment was not found.
    echo Please run EnvSetup\setup_env.bat first.
    echo.
    pause
    exit /b 1
)

if not exist "main.py" (
    echo main.py was not found in this folder.
    echo Please keep this bat file in the Audio Filter Tools project root.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "main.py"
if errorlevel 1 (
    echo.
    echo Audio Filter Tools exited with an error.
    echo Check logs\debug.log for details.
    echo.
    pause
)
endlocal
