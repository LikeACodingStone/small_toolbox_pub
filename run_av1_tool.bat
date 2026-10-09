@echo off
setlocal

pushd "%~dp0" || (
    echo Failed to enter tool folder: %~dp0
    pause
    exit /b 1
)

set "APP_DIR=%CD%"
set "PYTHON_EXE=python"
if exist "%APP_DIR%\EnvSetup\venv-windows\Scripts\python.exe" set "PYTHON_EXE=%APP_DIR%\EnvSetup\venv-windows\Scripts\python.exe"

"%PYTHON_EXE%" "%APP_DIR%\av1_3d_video_tool.py"
set "EXIT_CODE=%ERRORLEVEL%"
popd
pause
exit /b %EXIT_CODE%
