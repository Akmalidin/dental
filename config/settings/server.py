"""
Production server settings — single-tenant (как development, который реально работает),
но с PostgreSQL, DEBUG=False, реальным SECRET_KEY, HTTPS и whitenoise.

Запуск:  gunicorn config.wsgi:application  (DJANGO_SETTINGS_MODULE=config.settings.server)

ВАЖНО: приложение разрабатывалось и тестировалось в single-tenant режиме
(config.settings.development, config.urls_dev). Мультитенантный base.py/production.py
здесь сознательно НЕ используется, чтобы развернуть именно то, что работает.
"""
from .development import *  # noqa  — single-tenant структура apps/middleware/urlconf
from decouple import config, Csv

# ─── Core ────────────────────────────────────────────────────────────────────
DEBUG = False
SECRET_KEY = config("SECRET_KEY")
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

# ─── PostgreSQL ──────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="sadaf_clinic"),
        "USER": config("DB_USER", default="sadaf"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
    }
}

# ─── Static (whitenoise, со сжатием, без manifest-хеширования) ────────────────
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

# ─── Security ────────────────────────────────────────────────────────────────
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# nginx терминирует TLS и редиректит http→https, поэтому в Django редирект выключен,
# чтобы не было петли. Включается через env, когда сертификаты установлены.
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)

CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="https://denta.tw1.ru,https://sadaf.denta.tw1.ru",
    cast=Csv(),
)

# ─── Logging (в консоль → journald через systemd) ────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"verbose": {"format": "[{asctime}] {levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "verbose"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
