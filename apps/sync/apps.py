from django.apps import AppConfig


class SyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sync"
    verbose_name = "Синхронизация"

    def ready(self):
        from django.conf import settings
        if getattr(settings, "OFFLINE_MODE", False):
            from .core import connect_offline_signals
            connect_offline_signals()
