"""Точка входа Phusion Passenger для Plesk (Python App).

В панели Plesk укажите:
  Application Startup File = passenger_wsgi.py
  Application Root = каталог с этим файлом (корень проекта)
  Переменная окружения DJANGO_SETTINGS_MODULE = config.settings.plesk
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.plesk")

from config.wsgi import application  # noqa: E402
