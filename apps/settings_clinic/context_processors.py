def clinic_settings(request):
    """Inject clinic settings and unread notification count into every template."""
    ctx = {"clinic_settings": None, "unread_notifications_count": 0, "enabled_modules": []}

    try:
        from .models import ClinicSettings
        cs = ClinicSettings.get()
        ctx["clinic_settings"] = cs
        # Enabled modules (tariff). Empty list = all enabled.
        all_keys = [m[0] for m in ClinicSettings.ALL_MODULES]
        ctx["enabled_modules"] = cs.enabled_modules if cs.enabled_modules else all_keys
    except Exception:
        pass

    if request.user.is_authenticated:
        try:
            from apps.notifications.models import Notification
            ctx["unread_notifications_count"] = Notification.objects.filter(
                user=request.user, is_read=False
            ).count()
        except Exception:
            pass

    return ctx
