"""
ЛОКАЛЬНЫЙ ОФФЛАЙН-РЕЖИМ.
Приложение работает на компьютере клиники (localhost), своя SQLite-база.
Данные клиники скачиваются с облака командой:  manage.py offline_pull
Синхронизация обратно:  manage.py offline_push
"""
from .development import *  # noqa
import os

OFFLINE_MODE = True

# Отдельная локальная база (копия данных клиники)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "offline.sqlite3",
    }
}

# Адрес облака для синхронизации
CLOUD_URL = os.environ.get("CLOUD_URL", "https://sadaf.denta.tw1.ru")

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
DEBUG = False
