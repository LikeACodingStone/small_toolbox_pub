@echo off
cd /d "%~dp0"
py -3 player.py
if errorlevel 1 pause
