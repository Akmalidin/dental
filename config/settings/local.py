"""
ЛОКАЛЬНЫЙ ОФФЛАЙН-РЕЖИМ.
Один компьютер в клинике — «локальный сервер» (своя SQLite-база), остальные
компьютеры/ноутбуки подключаются к нему через браузер по локальной Wi-Fi/LAN
сети (http://<IP сервера>:8765/) — как к обычному сайту, только по локальному
адресу. Единая база на всех — конфликтов между компьютерами внутри клиники нет.
Данные клиники скачиваются с облака командой:  manage.py offline_pull
Синхронизация обратно:  manage.py offline_push
"""
from .development import *  # noqa
import os
import sys

OFFLINE_MODE = True

# Собранный .exe (PyInstaller --onefile) распаковывает все файлы во ВРЕМЕННУЮ
# папку при каждом запуске (BASE_DIR внутри неё) — если положить туда базу,
# все локальные данные будут стираться при каждом перезапуске программы!
# Поэтому база и файл настроек синхронизации хранятся рядом с самим .exe
# (постоянное место), а не в BASE_DIR.
if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).resolve().parent
else:
    DATA_DIR = BASE_DIR

# Свой секретный ключ для каждой установки (а не общий dev-ключ из кода):
# создаётся при первом запуске рядом с базой.
_key_file = DATA_DIR / "secret_key.txt"
try:
    SECRET_KEY = _key_file.read_text(encoding="utf-8").strip()
except OSError:
    SECRET_KEY = ""
if not SECRET_KEY:
    import secrets as _secrets
    SECRET_KEY = _secrets.token_urlsafe(50)
    try:
        _key_file.write_text(SECRET_KEY, encoding="utf-8")
    except OSError:
        pass

# Отдельная локальная база (копия данных клиники)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "offline.sqlite3",
    }
}

# Загруженные файлы (фото, документы) — туда же, рядом с .exe, а не во
# временную папку распаковки (иначе тоже терялись бы при перезапуске).
MEDIA_ROOT = DATA_DIR / "media"

# Адрес облака для синхронизации
CLOUD_URL = os.environ.get("CLOUD_URL", "https://soft.stom.asia")

# Разрешаем любой Host-заголовок: сервер слушает на 0.0.0.0 и доступен другим
# компьютерам клиники по локальному IP (сам сервер не выходит в интернет,
# поэтому это безопасно — только локальная сеть клиники).
ALLOWED_HOSTS = ["*"]
DEBUG = False
