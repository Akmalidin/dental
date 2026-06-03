@echo off
chcp 65001 >nul
cd /d "%~dp0"
set DJANGO_SETTINGS_MODULE=config.settings.local
echo ============================================
echo   SADAF — первичная настройка оффлайн-копии
echo ============================================
call venv\Scripts\activate.bat
echo Создание локальной базы...
python manage.py migrate --noinput
python manage.py collectstatic --noinput >nul 2>&1
echo.
set /p CLOUDURL="Адрес облака [https://sadaf.denta.tw1.ru]: "
if "%CLOUDURL%"=="" set CLOUDURL=https://sadaf.denta.tw1.ru
set /p LOGINV="Ваш логин: "
set /p PASSV="Ваш пароль: "
echo.
echo Скачивание данных вашей клиники...
python manage.py offline_pull --url %CLOUDURL% --login %LOGINV% --password %PASSV%
echo.
echo Готово. Теперь запускайте программу через offline_start.bat
pause
