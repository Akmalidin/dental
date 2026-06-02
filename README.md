# AKM SOFT — CLINIC

Медицинская CRM-система для стоматологических клиник.

---

## Быстрый старт (без Docker)

### 1. Требования

| Компонент | Версия |
|-----------|--------|
| Python | 3.12+ |
| PostgreSQL | 15+ |
| Redis | 7+ (опционально — только для Celery) |
| Node.js | 18+ (только для frontend) |

### 2. Установка PostgreSQL и создание БД

```sql
-- В psql от суперпользователя:
CREATE USER akm WITH PASSWORD 'ваш_пароль';
CREATE DATABASE akmsoft_clinic OWNER akm;
GRANT ALL PRIVILEGES ON DATABASE akmsoft_clinic TO akm;
```

### 3. Настройка окружения

```bash
cd akmsoft_clinic

# Скопируйте и отредактируйте .env
cp .env.example .env
# Укажите: DB_PASSWORD, SECRET_KEY, и другие нужные параметры
```

Минимальный `.env` для локальной разработки:

```env
SECRET_KEY=локальный-секрет-любой-строкой
DEBUG=True
DJANGO_SETTINGS_MODULE=config.settings.development
DB_HOST=localhost
DB_PORT=5432
DB_NAME=akmsoft_clinic
DB_USER=akm
DB_PASSWORD=ваш_пароль
REDIS_URL=redis://localhost:6379/0
SUPERADMIN_EMAIL=akmalmadakimov6@gmail.com
```

### 4. Запуск (Windows)

```bat
setup_local.bat
```

или вручную:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

set DJANGO_SETTINGS_MODULE=config.settings.development
python manage.py migrate_schemas --shared
python manage.py migrate_schemas
python manage.py runserver
```

### 5. Запуск (Linux / macOS)

```bash
chmod +x setup_local.sh
./setup_local.sh
python manage.py runserver
```

---

## Адреса после запуска

| URL | Описание |
|-----|----------|
| http://localhost:8000 | Главная страница / логин |
| http://localhost:8000/django-admin/ | Django Admin |
| http://localhost:8000/api/docs/ | Swagger UI (REST API) |
| http://localhost:8000/central/ | Панель суперадмина AKM SOFT |

**Логин по умолчанию:** `admin` / `admin123`

---

## Запуск с Celery (опционально, нужен Redis)

```bash
# Терминал 1 — Django
python manage.py runserver

# Терминал 2 — Celery worker
celery -A config worker -l info

# Терминал 3 — Celery Beat (расписание задач)
celery -A config beat -l info
```

---

## Запуск с Docker (production)

```bash
# Скопируйте .env
cp .env.example .env
# Отредактируйте .env

docker compose up -d
docker compose exec web python manage.py migrate_schemas --shared
docker compose exec web python manage.py migrate_schemas
docker compose exec web python manage.py createsuperuser
```

---

## Структура проекта

```
akmsoft_clinic/
├── config/              # Django конфигурация (settings, urls, celery)
├── apps/
│   ├── tenants/         # Мультитенантность (django-tenants)
│   ├── users/           # Аутентификация, роли, филиалы
│   ├── patients/        # Пациенты
│   ├── treatments/      # Приёмы и процедуры
│   ├── appointments/    # Расписание / записи
│   ├── services/        # Услуги и категории
│   ├── finance/         # Платежи и расходы
│   ├── warehouse/       # Склад материалов
│   ├── medicines/       # Лекарства
│   ├── tasks/           # Задачи
│   ├── technicians/     # Технические специалисты
│   ├── notifications/   # Уведомления (in-app + Telegram)
│   ├── reports/         # Аналитика и экспорт
│   └── settings_clinic/ # Настройки клиники
├── central/             # Панель суперадмина AKM SOFT
├── frontend/            # Vue 3 + Vite + Tailwind
├── templates/           # Django HTML шаблоны
├── locale/              # Переводы (ru, ky)
├── nginx/               # Nginx конфигурация
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── setup_local.bat      # Установка Windows
└── setup_local.sh       # Установка Linux/macOS
```

---

## Роли и доступ

| Роль | Описание |
|------|----------|
| `superadmin` | Полный доступ + панель AKM SOFT |
| `admin_main` | Весь функционал клиники |
| `admin` | Пациенты, записи, финансы (просмотр) |
| `doctor` | Свои пациенты, приёмы, лекарства |
| `nurse` | Пациенты (просмотр), расписание |

---

## REST API

- **Base URL:** `/api/v1/`
- **Документация:** `/api/docs/` (Swagger UI)
- **Аутентификация:** Session (браузер) + JWT Bearer (мобильный/интеграции)

---

## Мультитенантность

Каждая клиника — отдельная PostgreSQL схема.

**Локально:** Домен `localhost` → демо-клиника  
**Production:** `clinic1.akmsoft.kg`, `clinic2.akmsoft.kg`, ...

Управление клиниками: `/central/tenants/`

---

## Технологии

- **Backend:** Python 3.12, Django 5.1, DRF, django-tenants
- **Frontend:** Vue 3, Vite, Tailwind CSS, FullCalendar.js
- **БД:** PostgreSQL 16
- **Кэш/Очередь:** Redis 7, Celery
- **Хранилище:** S3-совместимое (MinIO / DigitalOcean Spaces)
- **PDF:** WeasyPrint
- **Excel:** openpyxl
- **Уведомления:** python-telegram-bot
- **Инфраструктура:** Docker, Nginx, Cloudflare

---

© 2025 AKM SOFT. Все права защищены.
