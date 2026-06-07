"""
Development settings — SQLite, без Docker, без мультитенантности.
Запуск: python manage.py runserver
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = "dev-secret-key-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

# ─── SQLite ──────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ─── Installed apps (без django-tenants) ─────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "django_filters",
    "corsheaders",
    "simple_history",

    # Project apps
    "apps.users",
    "apps.patients",
    "apps.treatments",
    "apps.appointments",
    "apps.services",
    "apps.finance",
    "apps.warehouse",
    "apps.medicines",
    "apps.tasks",
    "apps.technicians",
    "apps.notifications",
    "apps.reports",
    "apps.settings_clinic",
    "apps.sync",

    # Tenants app — только модели центральной БД (Tenant, Subscription)
    "apps.tenants",
]

# ─── Middleware (без TenantMainMiddleware) ────────────────────────────────────
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.tenancy.CurrentClinicMiddleware",
    "apps.tenancy.TariffGuardMiddleware",
    "apps.tenancy.PublicSiteMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.tenancy.SectionAccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls_dev"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.settings_clinic.context_processors.clinic_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_USER_MODEL = "users.User"

AUTHENTICATION_BACKENDS = [
    "apps.users.backends.LoginBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# ─── Storage ─────────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ─── Cache (локальная память) ─────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# ─── Localisation ─────────────────────────────────────────────────────────────
LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Bishkek"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LANGUAGES = [
    ("ru", "Русский"),
    ("ky", "Кыргызча"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

# ─── DRF ─────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 15,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AKM SOFT — CLINIC API",
    "DESCRIPTION": "REST API для медицинской CRM-системы стоматологических клиник",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

import datetime
SIMPLE_JWT = {
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ACCESS_TOKEN_LIFETIME": datetime.timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": datetime.timedelta(days=7),
}

# ─── Misc ─────────────────────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CONTENT_TYPE_NOSNIFF = True
AXES_ENABLED = False

# ─── WhatsApp (Green-API) — ключи только из env, не в репозиторий ─────────────
GREENAPI_ENABLED = os.environ.get("GREENAPI_ENABLED", "") == "1"
GREENAPI_ID_INSTANCE = os.environ.get("GREENAPI_ID_INSTANCE", "")
GREENAPI_TOKEN = os.environ.get("GREENAPI_TOKEN", "")
GREENAPI_API_URL = os.environ.get("GREENAPI_API_URL", "https://api.greenapi.com")

# ─── Публичные сайты клиник (поддомены) ──────────────────────────────────────
APP_HOST = "app.denta.tw1.ru"           # хост CRM-системы
PUBLIC_BASE_DOMAIN = "denta.tw1.ru"     # <slug>.denta.tw1.ru → публичный сайт клиники

SUPERADMIN_EMAIL = "akmalmadakimov6@gmail.com"
TELEGRAM_BOT_TOKEN = ""

# Версия статики для cache-busting (бампать при изменении app.css/app.js)
ASSET_VERSION = "2026060516"

# ─── Web Push (VAPID) ─────────────────────────────────────────────────────────
VAPID_PUBLIC_KEY = "BCa37d_93xAyPXKEsL6DNjLwTiUKYDvVTgHGcSMx8mHEMrQ6SqMcy8nHESIVSpo6atWAd_dGqUtWO7UnzFXZOjw"
VAPID_PRIVATE_B64 = os.environ.get("VAPID_PRIVATE_B64", "")  # приватный ключ — только из env
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", "mailto:akmalmadakimov6@gmail.com")

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "apps": {"handlers": ["console"], "level": "DEBUG"},
    },
}

# Celery (опционально — если Redis не установлен, задачи просто не работают)
try:
    CELERY_BROKER_URL = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND = "redis://localhost:6379/1"
    CELERY_TASK_ALWAYS_EAGER = True  # выполнять задачи синхронно в dev
except Exception:
    pass
