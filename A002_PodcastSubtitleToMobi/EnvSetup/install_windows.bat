@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"
if not defined PYTHON_BIN set "PYTHON_BIN=python"
if not defined VENV_DIR set "VENV_DIR=%PROJECT_DIR%\.venv"

%PYTHON_BIN% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 'Python 3.10+ is required. Current version: %s' % '.'.join(map(str, sys.version_info[:3])))"
if errorlevel 1 exit /b 1

%PYTHON_BIN% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo Failed to create virtual environment.
    echo Make sure Python 3.10+ is installed and available on PATH.
    exit /b 1
)

"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 exit /b 1

echo Python dependencies are ready.
echo Virtual environment: %VENV_DIR%
echo.
echo Run web UI:
echo   start_windows.bat
exit /b 0