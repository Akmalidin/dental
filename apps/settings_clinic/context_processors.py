def clinic_settings(request):
    """Inject clinic settings and unread notification count into every template."""
    from django.conf import settings as dj_settings
    ctx = {"clinic_settings": None, "unread_notifications_count": 0, "enabled_modules": [],
           "offline_mode": getattr(dj_settings, "OFFLINE_MODE", False),
           "vapid_public_key": getattr(dj_settings, "VAPID_PUBLIC_KEY", "")}

    try:
        from .models import ClinicSettings
        cs = ClinicSettings.get()
        ctx["clinic_settings"] = cs
        # Доступные модули — из ТЕКУЩЕЙ клиники (per-clinic тариф). Пусто = все.
        all_keys = [m[0] for m in ClinicSettings.ALL_MODULES]
        from apps.tenancy import get_current_clinic
        cur = get_current_clinic()
        if cur is not None:
            ctx["enabled_modules"] = cur.enabled_modules if cur.enabled_modules else all_keys
        else:
            ctx["enabled_modules"] = all_keys
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

        # Переключатель клиник — только для суперадмина
        try:
            if request.user.is_superadmin:
                from apps.users.models import Clinic
                clinics = list(Clinic.objects.filter(is_active=True))
                ctx["nav_clinics"] = clinics
                acid = request.session.get("active_clinic")
                ctx["active_clinic"] = next((c for c in clinics if c.pk == acid), None)
        except Exception:
            pass

    return ctx
