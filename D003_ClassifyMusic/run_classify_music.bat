@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%LOCALAPPDATA%\ClassifyMusic\windows_venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PYTHON_CMD="

if exist "%PYTHON_EXE%" goto :validate_venv

goto :create_venv

:create_venv
echo Creating the Windows Python environment...
call :find_python
if errorlevel 1 goto :python_not_found

%PYTHON_CMD% -m venv "%VENV_DIR%"
if errorlevel 1 goto :venv_error

:validate_venv
if not exist "%PYTHON_EXE%" goto :venv_error

"%PYTHON_EXE%" -c "import sys" >nul 2>&1
if errorlevel 1 goto :broken_venv

"%PYTHON_EXE%" -m pip --version >nul 2>&1
if errorlevel 1 goto :pip_missing

"%PYTHON_EXE%" -c "import PyQt5" >nul 2>&1
if errorlevel 1 (
    echo Installing PyQt5. This is needed only once per environment...
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check --requirement "%SCRIPT_DIR%requirements.txt"
    if errorlevel 1 goto :package_install_error
)

if /i "%~1"=="--setup-only" exit /b 0

"%PYTHON_EXE%" "%SCRIPT_DIR%music_file_list_gui.py"
exit /b %errorlevel%

:find_python
rem Prefer the Python Launcher. Unlike the Windows Store alias, it selects a real Python 3 install.
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
        exit /b 0
    )
)

rem Also check the standard per-user CPython install location. This works immediately
rem after installation, before Windows has refreshed the PATH of the current session.
for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%~fP\python.exe" (
        "%%~fP\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_CMD="%%~fP\python.exe""
            exit /b 0
        )
    )
)

rem Fall back to an explicit python.exe path after excluding the Microsoft Store
rem App Execution Alias at WindowsApps\python.exe. That alias can report false success.
for /f "delims=" %%P in ('where python 2^>nul') do (
    echo(%%P| findstr /i /c:"\WindowsApps\python.exe" >nul
    if errorlevel 1 (
        "%%P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_CMD="%%P""
            exit /b 0
        )
    )
)
exit /b 1

:python_not_found
echo.
echo A usable Python 3 installation was not found.
echo Install CPython 3.8 or newer from https://www.python.org/downloads/windows/
echo and select "Add python.exe to PATH", "pip", and "Python Launcher" during setup.
goto :environment_error

:venv_error
echo.
echo Python was found, but it could not create the virtual environment above.
echo Ensure that your Python installation includes the venv and pip components,
echo and that this folder is writable.
goto :environment_error

:broken_venv
echo.
echo The existing virtual environment is incomplete or cannot run.
echo Recreating the application-managed environment with this computer's Python...
call :find_python
if errorlevel 1 goto :python_not_found

rem VENV_DIR is a fixed application cache in LocalAppData, never the selected music folder.
rmdir /s /q "%VENV_DIR%"
if exist "%VENV_DIR%" goto :venv_remove_error
goto :create_venv

:venv_remove_error
echo.
echo The broken application environment could not be removed.
echo Close programs using it, then delete "%VENV_DIR%" and run this launcher again.
goto :environment_error

:pip_missing
echo.
echo The virtual environment was created without pip.
echo Repair or reinstall Python with the pip component selected, then run again.
goto :environment_error

:package_install_error
echo.
echo PyQt5 could not be installed. The pip error above shows the specific cause.
echo Check your internet/proxy settings and that https://pypi.org is reachable.
goto :environment_error

:environment_error
echo.
echo Environment setup failed.
if /i not "%~1"=="--no-pause" pause
exit /b 1
