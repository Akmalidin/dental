@echo off
chcp 65001 >nul
cd /d "%~dp0"
set DJANGO_SETTINGS_MODULE=config.settings.local
call venv\Scripts\activate.bat
python manage.py migrate --noinput >nul 2>&1
python manage.py collectstatic --noinput >nul 2>&1
echo ============================================
echo   SADAF — оффлайн режим. Не закрывайте это окно.
echo   Программа открыта в браузере: http://127.0.0.1:8765
echo ============================================
start "" http://127.0.0.1:8765/
python manage.py runserver 127.0.0.1:8765 --noreload
