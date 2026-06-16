"""Plesk shared-hosting (Phusion Passenger) — single-tenant, SQLite, whitenoise.

Запуск: Passenger импортирует application из passenger_wsgi.py с
DJANGO_SETTINGS_MODULE=config.settings.plesk.

Не требует PostgreSQL/Celery/weasyprint — всё работает на SQLite, статика
раздаётся whitenoise. Напоминания WhatsApp — через cron-команду wa_reminders
(планировщик задач Plesk), не Celery.
"""
import os
from .development import *  # noqa  — single-tenant apps/middleware/urlconf, SQLite

# ─── Core ────────────────────────────────────────────────────────────────────
DEBUG = False
# Задайте переменную окружения SECRET_KEY в панели Plesk (Python App → Переменные).
SECRET_KEY = os.environ.get("SECRET_KEY", "plesk-temp-key-CHANGE-ME-in-panel")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

# ─── Static (whitenoise, со сжатием, без manifest-хеширования) ────────────────
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

# ─── Security (TLS терминирует nginx Plesk) ──────────────────────────────────
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS", "https://195.38.164.50"
).split(",")

# ─── Логи в консоль (попадают в лог Passenger) ───────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {"apps": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
