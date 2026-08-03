@echo off
setlocal
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" main.py
) else (
    python main.py
)
set APP_EXIT_CODE=%ERRORLEVEL%
popd
exit /b %APP_EXIT_CODE%
