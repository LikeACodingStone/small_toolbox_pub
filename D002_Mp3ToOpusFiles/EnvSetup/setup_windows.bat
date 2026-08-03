@echo off
setlocal
pushd "%~dp0\.."
python EnvSetup\setup_env.py %*
set SETUP_EXIT_CODE=%ERRORLEVEL%
popd
exit /b %SETUP_EXIT_CODE%
