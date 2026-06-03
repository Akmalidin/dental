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

        # Филиалы для переключателя в navbar
        try:
            from apps.users.models import Branch
            branches = list(Branch.objects.filter(is_active=True))
            ctx["nav_branches"] = branches
            active_id = request.session.get("active_branch")
            active = next((b for b in branches if b.pk == active_id), None)
            if active is None:
                active = next((b for b in branches if b.is_main), None) or (branches[0] if branches else None)
            ctx["active_branch"] = active
        except Exception:
            pass

    return ctx
