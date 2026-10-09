@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

if not exist installed mkdir installed
set PIP_CACHE_DIR=%CD%\installed\pip_cache
set TMP=%CD%\installed\tmp
set TEMP=%CD%\installed\tmp
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if not exist "%TMP%" mkdir "%TMP%"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Please install Python 3.9+ and add it to PATH.
    exit /b 1
)

if not exist .venv (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --cache-dir "%PIP_CACHE_DIR%"
python -m pip install -r requirements.txt --cache-dir "%PIP_CACHE_DIR%"

echo Environment setup complete.
echo Run: .venv\Scripts\python main.py
endlocal
