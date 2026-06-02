import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("akmsoft_clinic")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Daily admin report at 20:00 Bishkek time (14:00 UTC)
    "daily-admin-report": {
        "task": "apps.notifications.tasks.send_daily_admin_report",
        "schedule": crontab(hour=14, minute=0),
    },
    # Appointment reminders — check every 15 minutes
    "appointment-reminders": {
        "task": "apps.notifications.tasks.send_appointment_reminders",
        "schedule": crontab(minute="*/15"),
    },
    # Check low warehouse stock daily at 09:00 UTC
    "warehouse-low-stock-check": {
        "task": "apps.warehouse.tasks.check_low_stock",
        "schedule": crontab(hour=9, minute=0),
    },
}

app.conf.task_routes = {
    "apps.notifications.tasks.*": {"queue": "notifications"},
    "apps.reports.tasks.*": {"queue": "reports"},
    "*": {"queue": "default"},
}
