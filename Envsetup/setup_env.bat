@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "CODE_DIR=%PROJECT_ROOT%\code"
set "VENV_DIR=%CODE_DIR%\.venv"
set "REQUIREMENTS_FILE=%CODE_DIR%\requirements.txt"

if not exist "%REQUIREMENTS_FILE%" (
    echo Requirements file not found: %REQUIREMENTS_FILE%
    exit /b 1
)

set "PYTHON_EXE="
set "PYTHON_ARGS="
where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
) else (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo Python 3 was not found. Install Python 3 and run this script again.
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment: %VENV_DIR%
    "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
    if errorlevel 1 exit /b 1
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
echo Installing requirements from %REQUIREMENTS_FILE%
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS_FILE%"
if errorlevel 1 exit /b 1

echo Environment ready: %VENV_DIR%
echo Run the toolbox with: %PROJECT_ROOT%\run_toolbox_win.bat
exit /b 0
