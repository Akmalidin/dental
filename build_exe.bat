@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Сборка единого .exe оффлайн-приложения (PyInstaller).
REM Запускать на машине с установленным проектом + venv.
call venv\Scripts\activate.bat
pip install pyinstaller -q
echo Сборка SADAF.exe ... (займёт пару минут)
pyinstaller --noconfirm --onefile --noconsole ^
  --name "SADAF" ^
  --icon "static\icon.ico" ^
  --collect-all django ^
  --collect-all rest_framework ^
  --collect-submodules apps ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "staticfiles;staticfiles" ^
  --hidden-import "config.settings.local" ^
  offline_launcher.py
echo.
echo Готово: dist\SADAF.exe  (иконка приложения)
pause
