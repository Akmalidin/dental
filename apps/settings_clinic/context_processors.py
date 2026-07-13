def clinic_settings(request):
    """Inject clinic settings and unread notification count into every template."""
    from django.conf import settings as dj_settings
    ctx = {"clinic_settings": None, "unread_notifications_count": 0, "enabled_modules": [],
           "offline_mode": getattr(dj_settings, "OFFLINE_MODE", False),
           "vapid_public_key": getattr(dj_settings, "VAPID_PUBLIC_KEY", ""),
           "asset_v": getattr(dj_settings, "ASSET_VERSION", "1"),
           # Рабочее окно клиники (для ограничения выбора времени везде)
           "work_start": "09:00", "work_end": "21:00"}

    from apps.tenancy import get_current_clinic
    cur = get_current_clinic()
    try:
        from .models import ClinicSettings
        cs = ClinicSettings.get()
        ctx["clinic_settings"] = cs
        # Рабочее окно: самое раннее открытие и самое позднее закрытие по дням недели
        wh = cs.working_hours if isinstance(cs.working_hours, dict) else {}
        starts, ends = [], []
        for v in wh.values():
            if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] and v[1]:
                starts.append(str(v[0])); ends.append(str(v[1]))
        if starts and ends:
            ctx["work_start"] = min(starts)
            ctx["work_end"] = max(ends)
        # Доступные модули — из ТЕКУЩЕЙ клиники (per-clinic тариф). Пусто = все.
        all_keys = [m[0] for m in ClinicSettings.ALL_MODULES]
        if cur is not None:
            ctx["enabled_modules"] = cur.enabled_modules if cur.enabled_modules else all_keys
        else:
            ctx["enabled_modules"] = all_keys
    except Exception:
        pass

    if request.user.is_authenticated:
        # Персональные доступы к разделам (для сайдбара)
        try:
            ctx["user_sections"] = request.user.nav_sections
        except Exception:
            from apps.users.models import SECTION_KEYS
            ctx["user_sections"] = set(SECTION_KEYS)

        try:
            from apps.notifications.models import Notification
            ncount = Notification.objects.filter(user=request.user, is_read=False)
            if cur is not None:
                ncount = ncount.filter(clinic=cur)
            ctx["unread_notifications_count"] = ncount.count()
        except Exception:
            pass

        # Непрочитанные WhatsApp-входящие (для бейджа в сайдбаре, только админам)
        try:
            if getattr(request.user, "is_admin", False) or getattr(request.user, "is_superadmin", False):
                from apps.notifications.models import WaMessage
                wq = WaMessage.all_clinics.filter(direction="in", read=False)
                if cur is not None:
                    wq = wq.filter(clinic=cur)
                ctx["wa_unread"] = wq.count()
        except Exception:
            pass

        # Возможные дубли пациентов (по совпадающему номеру телефона) — бейдж
        # в сайдбаре у «Пациенты», чтобы персонал не держал это в голове сам.
        try:
            from apps.patients.models import Patient, SharedPhoneNumber
            from django.db.models import Count
            confirmed = set(SharedPhoneNumber.objects.values_list("phone_norm", flat=True))
            dupe_groups = (Patient.objects.exclude(phone_norm="")
                           .exclude(phone_norm__in=confirmed)
                           .values("phone_norm").annotate(c=Count("id")).filter(c__gt=1))
            ctx["dupe_patients_count"] = sum(g["c"] for g in dupe_groups)
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
