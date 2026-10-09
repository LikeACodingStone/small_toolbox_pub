@echo off
setlocal
cd /d "%~dp0"
set "CODE_DIR=%~dp0code"
set "PYTHON=%~dp0Envsetup\environments\toolbox\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Virtual environment not found. Run Envsetup\setup_env.bat first.
    exit /b 1
)
"%PYTHON%" "%CODE_DIR%\toolbox.py" %*
