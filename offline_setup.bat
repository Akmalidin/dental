@echo off
cd /d "%~dp0"
set DJANGO_SETTINGS_MODULE=config.settings.local
call venv\Scripts\activate.bat
python offline.py setup
