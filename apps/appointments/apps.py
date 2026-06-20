from django.apps import AppConfig


class AppointmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.appointments"
    verbose_name = "Записи"

    def ready(self):
        from . import signals  # noqa: F401
