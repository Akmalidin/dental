@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Installing PyInstaller...
python -m pip install pyinstaller -q
echo Collecting static...
set DJANGO_SETTINGS_MODULE=config.settings.local
python manage.py collectstatic --noinput
echo Building SADAF.exe (takes a few minutes)...
python -m PyInstaller --noconfirm --onefile --noconsole --name SADAF --icon "static\icon.ico" --collect-all django --collect-all rest_framework --collect-all corsheaders --collect-all simple_history --collect-submodules apps --add-data "templates;templates" --add-data "static;static" --add-data "staticfiles;staticfiles" --add-data "locale;locale" --hidden-import config.settings.local --hidden-import pywebpush offline_launcher.py
echo.
echo Done. Result: dist\SADAF.exe
pause
