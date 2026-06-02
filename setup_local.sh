#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  AKM SOFT CLINIC — Local Setup Script (Linux / macOS)
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo ""
echo "  AKM SOFT - CLINIC  (локальная разработка)"
echo "─────────────────────────────────────────────────────────────────────────"

# Check Python
python3 --version >/dev/null 2>&1 || { echo "[ОШИБКА] Установите Python 3.12+"; exit 1; }

# .env
[ ! -f .env ] && cp .env.example .env && echo "[INFO] Создан .env из .env.example — отредактируйте его"

# Virtualenv
[ ! -d .venv ] && python3 -m venv .venv && echo "[INFO] Создано виртуальное окружение"
source .venv/bin/activate

# Install deps
pip install -r requirements.txt -q

export DJANGO_SETTINGS_MODULE=config.settings.development

# Migrate
echo "[INFO] Миграции..."
python manage.py migrate_schemas --shared
python manage.py migrate_schemas

# Superuser
echo "[INFO] Проверка суперадмина..."
python manage.py shell -c "
from django.contrib.auth import get_user_model
from django.conf import settings
User = get_user_model()
email = settings.SUPERADMIN_EMAIL
if not User.objects.filter(email=email).exists():
    from apps.users.models import Role
    role, _ = Role.objects.get_or_create(name='superadmin')
    user = User.objects.create_superuser(login='admin', email=email, password='admin123', name='AKM SuperAdmin')
    user.role = role
    user.save()
    print('Суперадмин создан: admin / admin123')
else:
    print('Суперадмин уже существует')
"

# Demo tenant
echo "[INFO] Тестовая клиника..."
python manage.py shell -c "
from apps.tenants.models import Tenant, Domain, Subscription
from datetime import date
if not Tenant.objects.filter(schema_name='demo').exists():
    t = Tenant(schema_name='demo', name='Демо клиника', slug='demo', owner_email='demo@akmsoft.kg')
    t.save()
    Domain.objects.create(domain='localhost', tenant=t, is_primary=True)
    Subscription.objects.create(tenant=t, plan='trial', started_at=date.today())
    print('Тестовая клиника создана')
else:
    print('Уже существует')
"

python manage.py collectstatic --noinput >/dev/null 2>&1 || true

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Запустите: python manage.py runserver"
echo "  Адрес:     http://localhost:8000"
echo "  Логин:     admin / admin123"
echo "  API Docs:  http://localhost:8000/api/docs/"
echo "═══════════════════════════════════════════════════════════════"
