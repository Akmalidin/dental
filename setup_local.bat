@echo off
chcp 65001 >nul
setlocal

echo.
echo  AKM SOFT - CLINIC  (SQLite / local dev)
echo  =========================================

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.12+
    pause
    exit /b 1
)

set DJANGO_SETTINGS_MODULE=config.settings.development

:: Create virtualenv
if not exist .venv (
    echo [INFO] Creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create venv
        pause & exit /b 1
    )
)

:: Activate
call .venv\Scripts\activate.bat

:: Install dependencies
echo [INFO] Installing packages...
pip install -r requirements.txt -q --no-warn-script-location
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed
    pause & exit /b 1
)

:: Migrations
echo [INFO] Running migrations...
python manage.py migrate
if %errorlevel% neq 0 (
    echo [ERROR] migrate failed
    pause & exit /b 1
)

:: Init dev data
echo [INFO] Creating superadmin and demo clinic...
python manage.py init_dev

:: Collect static
echo [INFO] Collecting static files...
python manage.py collectstatic --noinput -v 0

echo.
echo  =====================================================
echo   Ready!
echo   URL:      http://127.0.0.1:8000
echo   Login:    admin
echo   Password: admin123
echo   Swagger:  http://127.0.0.1:8000/api/docs/
echo   Admin:    http://127.0.0.1:8000/django-admin/
echo  =====================================================
echo.

python manage.py runserver
