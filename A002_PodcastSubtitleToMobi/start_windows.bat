@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "LAUNCH_LOG=%~dp0start_windows_debug.log"
set "APP_LOG_FILE=%~dp0app_ui_debug.log"
set "APP_HOST=127.0.0.1"
set "APP_OPEN_BROWSER=1"
set "APP_PORT="

set "LAUNCH_TIME="
for /f "delims=" %%T in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyy-MM-ddTHH:mm:ss.fff"') do set "LAUNCH_TIME=%%T"

>>"%LAUNCH_LOG%" echo.
>>"%LAUNCH_LOG%" echo [%LAUNCH_TIME%] Launcher started.
>>"%LAUNCH_LOG%" echo Working directory: %CD%

set "PYTHONW_PATH="
for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PYTHONW_PATH set "PYTHONW_PATH=%%P"

if not defined PYTHONW_PATH (
    >>"%LAUNCH_LOG%" echo ERROR: pythonw.exe was not found on PATH.
    >>"%LAUNCH_LOG%" echo Run: python -m pip install -r requirement.txt
    exit /b 1
)

>>"%LAUNCH_LOG%" echo Python executable: %PYTHONW_PATH%
start "" "%PYTHONW_PATH%" "%~dp0app_ui.py"
set "START_RESULT=%ERRORLEVEL%"
>>"%LAUNCH_LOG%" echo start command result: %START_RESULT%
if not "%START_RESULT%"=="0" (
    >>"%LAUNCH_LOG%" echo ERROR: Failed to create the UI process.
    exit /b %START_RESULT%
)
>>"%LAUNCH_LOG%" echo UI process launch requested successfully.
exit /b 0
