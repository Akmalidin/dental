# Шаг 1 — безопасные фиксы (без изменения поведения программы для пользователя)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить 4 находки из аудита архитектуры (см. `docs/` / отчёт-артефакт от 2026-07-06), которые сегодня либо тихо не работают, либо являются дырой в защите — без изменения видимого пользователю поведения CRM.

**Architecture:** Точечные правки в существующих модулях (`apps/warehouse/tasks.py`, `config/settings/*`, `config/wsgi.py`, `deploy/*`) плюс первые тесты в проекте, где тестов раньше не было вообще. Ничего не рефакторится сверх необходимого для фикса.

**Tech Stack:** Django 5.1.4, Celery 5.4 (task queue), Redis (broker), django-axes 6.5.1 (brute-force protection), Django `TestCase`/`SimpleTestCase` (без pytest — в проекте его нет и мы не вводим новую тест-инфраструктуру ради 4 фиксов).

## Global Constraints

- Не менять поведение программы для пользователя. Каждая задача — либо чинит то, что и так должно было работать (задача 1, 4), либо добавляет защиту, которая раньше отсутствовала (задача 3), либо чинит хрупкость конфигурации (задача 2). Ни одна задача не меняет бизнес-логику приёмов/пациентов/финансов.
- Реальный прод — systemd + gunicorn на сервере SADAF (`deploy/sadaf.service`, домен `denta.tw1.ru`, `config.settings.server`). Локальная разработка — SQLite + `config.settings.development` (дефолт `manage.py`).
- Тестов в проекте нет нигде. Для этого плана заводим их по ходу (см. вопрос пользователя) — только для кода, который реально меняем, без ретроактивного покрытия остального проекта.
- Каждая задача коммитится отдельно.
- Шаги, требующие доступа к боевому серверу (systemctl, apt), явно помечены **[РУЧНОЙ ШАГ НА СЕРВЕРЕ]** — их выполняет пользователь по SSH, агент их не запускает.

---

### Task 1: Починить `check_low_stock` (Celery-задача проверки остатков всегда молчала)

**Files:**
- Modify: `apps/warehouse/tasks.py`
- Create: `apps/warehouse/tests.py`

**Interfaces:**
- Consumes: `apps.warehouse.models.Product` (поля `quantity`, `min_qty`, `is_active`, `name`, `unit` — уже существуют, `apps/warehouse/models.py:33-61`), `apps.notifications.utils.notify_admins(text: str)` (уже существует, `apps/notifications/utils.py:20`).
- Produces: ничего нового наружу — сигнатура `check_low_stock()` (Celery-задача, без аргументов) не меняется.

- [ ] **Step 1: Написать падающий тест**

```python
# apps/warehouse/tests.py
from unittest.mock import patch

from django.test import TestCase

from apps.warehouse.models import Product
from apps.warehouse.tasks import check_low_stock


class CheckLowStockTaskTests(TestCase):
    def setUp(self):
        self.low = Product.objects.create(
            name="Анестетик Ультракаин", unit="уп.", quantity="2.000", min_qty="5.000", is_active=True,
        )
        self.ok = Product.objects.create(
            name="Перчатки нитриловые", unit="уп.", quantity="50.000", min_qty="10.000", is_active=True,
        )
        self.inactive_low = Product.objects.create(
            name="Списанный материал", unit="шт.", quantity="0.000", min_qty="1.000", is_active=False,
        )

    @patch("apps.warehouse.tasks.notify_admins")
    def test_notifies_only_for_active_products_below_min_qty(self, mock_notify):
        check_low_stock()

        self.assertEqual(mock_notify.call_count, 1)
        text = mock_notify.call_args[0][0]
        self.assertIn("Анестетик Ультракаин", text)
        self.assertNotIn("Перчатки нитриловые", text)
        self.assertNotIn("Списанный материал", text)

    @patch("apps.warehouse.tasks.notify_admins")
    def test_no_notification_when_stock_is_sufficient(self, mock_notify):
        Product.objects.filter(pk=self.low.pk).update(quantity="10.000")

        check_low_stock()

        mock_notify.assert_not_called()
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `python manage.py test apps.warehouse.tests -v 2`
Expected: FAIL — `test_notifies_only_for_active_products_below_min_qty` падает с `AssertionError: 0 != 1` (сейчас `models_F_qty()` всегда возвращает `None`, поэтому `quantity__lte=None` не находит вообще ничего).

- [ ] **Step 3: Исправить задачу**

```python
# apps/warehouse/tasks.py
from celery import shared_task
from django.db.models import F


@shared_task(name="apps.warehouse.tasks.check_low_stock")
def check_low_stock():
    from .models import Product
    from apps.notifications.utils import notify_admins

    low_stock = Product.objects.filter(is_active=True, quantity__lte=F("min_qty"))
    if low_stock.exists():
        lines = ["⚠️ Низкий остаток:\n"]
        for p in low_stock:
            lines.append(f"• {p.name}: {p.quantity} {p.unit} (мин: {p.min_qty})")
        notify_admins("\n".join(lines))
```

Полностью удалить функцию `models_F_qty()` (строки 17-20 в старой версии файла) — она была костылём-заглушкой и больше не нужна.

- [ ] **Step 4: Запустить тест и убедиться, что он проходит**

Run: `python manage.py test apps.warehouse.tests -v 2`
Expected: PASS — оба теста зелёные.

- [ ] **Step 5: Коммит**

```bash
git add apps/warehouse/tasks.py apps/warehouse/tests.py
git commit -m "fix(warehouse): check_low_stock never matched any product (models_F_qty stub always returned None)"
```

---

### Task 2: Убрать риск падения прода на мёртвый мультитенантный settings-модуль

**Files:**
- Modify: `config/wsgi.py`
- Modify: `manage.py:9` (комментарий)
- Modify: `deploy/sadaf.service`

**Interfaces:**
- Consumes: ничего нового.
- Produces: `DJANGO_SETTINGS_MODULE` теперь по умолчанию (без переменной окружения) указывает на `config.settings.development` — тот же дефолт, что уже используется в `manage.py:8`, — вместо неиспользуемого `config.settings.production`.

- [ ] **Step 1: Поправить дефолт в `wsgi.py`**

```python
# config/wsgi.py
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

application = get_wsgi_application()
```

- [ ] **Step 2: Поправить вводящий в заблуждение комментарий в `manage.py`**

```python
# manage.py:8-9
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    # Подсказка: для боевого сервера SADAF используй config.settings.server (см. deploy/sadaf.service)
```

- [ ] **Step 3: Добавить явный fallback переменной окружения в systemd-юнит прода**

```ini
# deploy/sadaf.service — добавить строку в секцию [Service] ДО EnvironmentFile,
# чтобы .env (если в нём есть DJANGO_SETTINGS_MODULE) продолжал иметь приоритет,
# но при потере переменной из .env сервис не падал на дефолт из wsgi.py.
[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/var/www/sadaf
Environment=DJANGO_SETTINGS_MODULE=config.settings.server
EnvironmentFile=/var/www/sadaf/.env
ExecStart=/var/www/sadaf/venv/bin/gunicorn config.wsgi:application \
    --bind 127.0.0.1:8021 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
Restart=always
RestartSec=3
KillMode=mixed
```

- [ ] **Step 4: Проверить, что Django по-прежнему поднимается локально с дефолтными настройками**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).` (без переменной `DJANGO_SETTINGS_MODULE` в окружении команда использует dev-настройки, как и раньше — поведение локальной разработки не изменилось).

- [ ] **Step 5: Коммит**

```bash
git add config/wsgi.py manage.py deploy/sadaf.service
git commit -m "fix(config): stop defaulting to unused multi-tenant production.py; add explicit settings fallback to systemd unit"
```

**[РУЧНОЙ ШАГ НА СЕРВЕРЕ]** после деплоя этой задачи выполнить на боевом сервере:
```bash
sudo systemctl daemon-reload
sudo systemctl restart sadaf.service
sudo systemctl status sadaf.service   # убедиться, что Active: active (running)
```

---

### Task 3: Включить защиту от подбора пароля (django-axes) в реальной цепочке настроек

**Files:**
- Modify: `requirements.txt`
- Modify: `config/settings/development.py`
- Create: `apps/users/tests_axes.py`

**Interfaces:**
- Consumes: `apps.users.forms.LoginForm` (уже вызывает `django.contrib.auth.authenticate(self.request, ...)` с `request` — обязательное условие для axes, `apps/users/forms.py:26`), `apps.users.views.login_view` (не меняется).
- Produces: после 5 неудачных попыток входа с одного IP — блокировка на 1 час (`AXES_FAILURE_LIMIT=5`, `AXES_COOLOFF_TIME=1`).

- [ ] **Step 1: Добавить зависимость**

```text
# requirements.txt — добавить строкой после django-simple-history==3.7.0
django-axes==6.5.1
```

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Подключить axes в settings (INSTALLED_APPS, MIDDLEWARE, AUTHENTICATION_BACKENDS)**

```python
# config/settings/development.py — в INSTALLED_APPS, после "simple_history" (строка 37)
    "simple_history",
    "axes",
```

```python
# config/settings/development.py — MIDDLEWARE, AxesMiddleware ДОЛЖЕН быть последним в списке
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.tenancy.ImpersonationMiddleware",
    "apps.tenancy.CurrentClinicMiddleware",
    "apps.tenancy.TariffGuardMiddleware",
    "apps.tenancy.PublicSiteMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.tenancy.SectionAccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "axes.middleware.AxesMiddleware",
]
```

```python
# config/settings/development.py — AxesStandaloneBackend ДОЛЖЕН быть первым в списке
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.users.backends.LoginBackend",
    "django.contrib.auth.backends.ModelBackend",
]
```

```python
# config/settings/development.py:192 — заменить строку "AXES_ENABLED = False" на:
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # часов
AXES_RESET_ON_SUCCESS = True
```

- [ ] **Step 3: Применить миграции axes (создаёт свои таблицы — `AccessAttempt`, `AccessLog`, `AccessFailureLog`)**

Run: `python manage.py migrate axes`
Expected: `Applying axes.0001_initial... OK` (и последующие миграции пакета).

- [ ] **Step 4: Написать падающий тест реальной блокировки**

```python
# apps/users/tests_axes.py
from axes.utils import reset

from django.test import TestCase, Client
from django.contrib.auth import get_user_model

User = get_user_model()


class AxesLockoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            login="test_doctor", email="test_doctor@example.com", password="correct-horse-battery-staple",
        )
        self.client = Client()

    def tearDown(self):
        reset(username="test_doctor")

    def test_locks_out_after_five_failed_attempts(self):
        for _ in range(5):
            self.client.post("/login/", {"login": "test_doctor", "password": "wrong-password"})

        # 6-я попытка — уже с ПРАВИЛЬНЫМ паролем, но должна быть заблокирована axes
        response = self.client.post(
            "/login/", {"login": "test_doctor", "password": "correct-horse-battery-staple"}
        )

        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_correct_password_works_before_limit_reached(self):
        for _ in range(4):
            self.client.post("/login/", {"login": "test_doctor", "password": "wrong-password"})

        response = self.client.post(
            "/login/", {"login": "test_doctor", "password": "correct-horse-battery-staple"}, follow=True
        )

        self.assertTrue(response.wsgi_request.user.is_authenticated)
```

- [ ] **Step 5: Запустить тест — на этом шаге он должен УЖЕ проходить (axes подключён в Step 2-3)**

Run: `python manage.py test apps.users.tests_axes -v 2`
Expected: PASS. Если `test_locks_out_after_five_failed_attempts` падает с `AssertionError: True is not false` — проверить порядок `AUTHENTICATION_BACKENDS`/`MIDDLEWARE` из Step 2 (самая частая причина — `AxesStandaloneBackend` не первый или `AxesMiddleware` не последний).

- [ ] **Step 6: Ручная проверка, что обычный вход не сломан**

Run: `python manage.py test apps.users -v 2` (если в apps/users уже есть другие тесты — их сейчас нет, проверить, что команда не падает на импортах)

- [ ] **Step 7: Коммит**

```bash
git add requirements.txt config/settings/development.py apps/users/tests_axes.py
git commit -m "feat(security): enable django-axes brute-force protection in the settings chain actually used in production"
```

**[РУЧНОЙ ШАГ НА СЕРВЕРЕ]** после деплоя:
```bash
cd /var/www/sadaf
./venv/bin/pip install -r requirements_server.txt -q   # requirements_server.txt наследует requirements.txt через -r
./venv/bin/python manage.py migrate axes --noinput
sudo systemctl restart sadaf.service
```

---

### Task 4: Дать периодическим Celery-задачам физическую возможность выполняться в проде

**Context:** Реальный прод (systemd + gunicorn) не запускает ни Celery worker, ни Celery Beat — `deploy/` содержит только юнит для gunicorn. `requirements_server.txt` намеренно не включает `celery`/`redis`. При этом `CELERY_TASK_ALWAYS_EAGER = True` из `development.py:236-242` наследуется в `server.py` и не переопределяется. Итог: `check_low_stock` (Task 1) и `send_appointment_reminders`/`send_daily_admin_report` физически не запускаются на боевом сервере ни при каких условиях — там некому читать `app.conf.beat_schedule` на расписании.

**Files:**
- Modify: `requirements_server.txt`
- Modify: `config/settings/server.py`
- Create: `deploy/sadaf-celery.service`
- Create: `deploy/sadaf-celerybeat.service`
- Modify: `deploy/update.sh`
- Create: `config/test_settings.py`

**Interfaces:**
- Consumes: `config/celery.py` (уже существует, не меняется — `app.conf.beat_schedule` и `app.conf.task_routes` уже корректно описывают 3 задачи).
- Produces: `config.settings.server.CELERY_TASK_ALWAYS_EAGER == False`, `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` берутся из `.env` с дефолтом на локальный Redis (сервис и БД-приложение на одной машине).

- [ ] **Step 1: Написать падающий тест-регрессию для настроек**

```python
# config/test_settings.py
import importlib
import os

from django.test import SimpleTestCase


REQUIRED_ENV = {
    "SECRET_KEY": "test-secret-key",
    "DB_PASSWORD": "test-db-password",
    "ALLOWED_HOSTS": "example.com",
}


class ServerSettingsTests(SimpleTestCase):
    """Прод (config.settings.server) не должен молча наследовать eager-режим Celery из dev."""

    def _reload_server_settings(self):
        old = {k: os.environ.get(k) for k in REQUIRED_ENV}
        os.environ.update(REQUIRED_ENV)
        try:
            module = importlib.import_module("config.settings.server")
            return importlib.reload(module)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_celery_task_always_eager_is_disabled_in_production(self):
        server_settings = self._reload_server_settings()
        self.assertFalse(server_settings.CELERY_TASK_ALWAYS_EAGER)

    def test_celery_broker_and_backend_are_configured(self):
        server_settings = self._reload_server_settings()
        self.assertTrue(server_settings.CELERY_BROKER_URL)
        self.assertTrue(server_settings.CELERY_RESULT_BACKEND)
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `python manage.py test config.test_settings -v 2`
Expected: FAIL на `test_celery_task_always_eager_is_disabled_in_production` — `CELERY_TASK_ALWAYS_EAGER` сейчас `True` (унаследовано из `development.py` и не переопределено в `server.py`).

- [ ] **Step 3: Переопределить Celery-настройки в `server.py`**

```python
# config/settings/server.py — добавить в конец файла
# ─── Celery (реальный broker, не eager-режим dev) ────────────────────────────
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_ALWAYS_EAGER = False
```

- [ ] **Step 4: Запустить тест и убедиться, что он проходит**

Run: `python manage.py test config.test_settings -v 2`
Expected: PASS.

- [ ] **Step 5: Добавить celery/redis в зависимости реального прода**

```text
# requirements_server.txt — заменить комментарий и добавить 2 строки
# Single-tenant production deps (PostgreSQL + gunicorn + celery, без django-tenants)
-r requirements.txt

psycopg2-binary==2.9.10
gunicorn==23.0.0
pywebpush==2.3.0
qrcode==8.0
celery==5.4.0
redis==5.2.0
```

- [ ] **Step 6: Создать systemd-юнит для Celery worker**

```ini
# deploy/sadaf-celery.service
[Unit]
Description=SADAF Clinic — Celery worker
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/sadaf
EnvironmentFile=/var/www/sadaf/.env
Environment=DJANGO_SETTINGS_MODULE=config.settings.server
ExecStart=/var/www/sadaf/venv/bin/celery -A config worker \
    --loglevel=info \
    --queues=default,notifications,reports \
    --concurrency=2
Restart=always
RestartSec=3
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 7: Создать systemd-юнит для Celery Beat**

```ini
# deploy/sadaf-celerybeat.service
[Unit]
Description=SADAF Clinic — Celery beat (периодические задачи)
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/sadaf
EnvironmentFile=/var/www/sadaf/.env
Environment=DJANGO_SETTINGS_MODULE=config.settings.server
ExecStart=/var/www/sadaf/venv/bin/celery -A config beat \
    --loglevel=info \
    --pidfile=/var/www/sadaf/celerybeat.pid
Restart=always
RestartSec=3
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 8: Обновить деплой-скрипт, чтобы он перезапускал новые сервисы**

```bash
# deploy/update.sh — заменить последний блок (chown + restart)
echo ">>> chown + restart"
chown -R www-data:www-data "$APP"
systemctl restart sadaf.service sadaf-celery.service sadaf-celerybeat.service
sleep 2
systemctl is-active sadaf.service
systemctl is-active sadaf-celery.service
systemctl is-active sadaf-celerybeat.service
echo ">>> done"
```

- [ ] **Step 9: Коммит**

```bash
git add config/settings/server.py config/test_settings.py requirements_server.txt deploy/sadaf-celery.service deploy/sadaf-celerybeat.service deploy/update.sh
git commit -m "fix(deploy): give periodic Celery tasks a worker/beat process to run on in production"
```

**[РУЧНОЙ ШАГ НА СЕРВЕРЕ]** — это единственная задача, которая требует установки нового системного пакета и включения новых сервисов. Выполнить по SSH на сервере SADAF **один раз**:

```bash
# 1. Установить и включить Redis (брокер сообщений для Celery)
sudo apt-get update && sudo apt-get install -y redis-server
sudo systemctl enable --now redis-server

# 2. Скопировать новые unit-файлы и подключить их к systemd
sudo cp /var/www/sadaf/deploy/sadaf-celery.service /etc/systemd/system/
sudo cp /var/www/sadaf/deploy/sadaf-celerybeat.service /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Обновить зависимости и включить сервисы
cd /var/www/sadaf
./venv/bin/pip install -r requirements_server.txt -q
sudo systemctl enable --now sadaf-celery.service
sudo systemctl enable --now sadaf-celerybeat.service

# 4. Проверить, что всё поднялось
sudo systemctl status sadaf-celery.service sadaf-celerybeat.service
./venv/bin/celery -A config inspect ping   # ожидается: pong от воркера
```

---

## Self-Review

- **Покрытие:** все 4 пункта из «Шага 1» отчёта-аудита (models_F_qty, DJANGO_SETTINGS_MODULE/wsgi.py дефолт, axes, отсутствие Celery worker/beat в проде) закрыты задачами 1-4 соответственно.
- **Заглушки:** ни одного `TODO`/«добавить обработку ошибок» — все шаги содержат готовый код.
- **Согласованность типов/имён:** `check_low_stock()` (Task 1) не меняет сигнатуру; `config.settings.server.CELERY_BROKER_URL`, введённый в Task 4, используется в новых unit-файлах через `.env`, а не через python-импорт — расхождений имён нет.
- **Порядок задач:** 1 и 3 полностью независимы друг от друга и от 2/4; 4 логически замыкает 1 (без воркера фикс из Task 1 не имеет эффекта в проде) — поэтому в плане Task 4 идёт последним, но при желании можно исполнять 1-3 в любом порядке параллельно, если выбран subagent-driven режим.
