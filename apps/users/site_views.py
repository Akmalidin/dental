"""Публичный сайт клиники (поддомен). Без логина. Клиника берётся из request.public_clinic
(ставится PublicSiteMiddleware)."""
from django.shortcuts import render
from django.http import Http404


def _ctx(request):
    clinic = getattr(request, "public_clinic", None)
    site = getattr(request, "public_site", None)
    if clinic is None or site is None:
        raise Http404("Сайт недоступен")
    return clinic, site


def public_home(request):
    clinic, site = _ctx(request)

    doctors = []
    if site.show_doctors:
        from apps.users.models import clinic_doctors
        doctors = list(clinic_doctors(clinic)[:24])

    services = []
    if site.show_services:
        from apps.services.models import Service
        services = list(
            Service.objects.filter(is_active=True).select_related("category")
            .order_by("category__sort_order", "name")[:60]
        )

    from apps.users.models import Branch
    branches = list(Branch.objects.filter(is_active=True))
    map_points = [
        {"name": b.name, "address": b.address, "phone": b.phone,
         "lat": b.latitude, "lng": b.longitude}
        for b in branches if b.latitude is not None and b.longitude is not None
    ]

    return render(request, "public/home.html", {
        "clinic": clinic, "site": site,
        "doctors": doctors, "services": services, "branches": branches,
        "map_points": map_points,
    })


def public_service(request, pk):
    """Полная страница об услуге/лечении."""
    clinic, site = _ctx(request)
    from apps.services.models import Service
    service = Service.objects.filter(pk=pk, is_active=True).select_related("category").first()
    if service is None:
        raise Http404("Услуга не найдена")
    related = list(
        Service.objects.filter(is_active=True, category=service.category)
        .exclude(pk=service.pk)[:6]
    )
    return render(request, "public/service.html", {
        "clinic": clinic, "site": site, "service": service, "related": related,
    })


WORK_START, WORK_END, SLOT_HOURS = 9, 18, 1  # рабочие часы и шаг слота


def public_book(request):
    """Страница онлайн-записи."""
    clinic, site = _ctx(request)
    if not site.show_booking:
        raise Http404("Запись недоступна")
    from apps.users.models import clinic_doctors
    from apps.services.models import Service
    doctors = list(clinic_doctors(clinic))
    services = list(Service.objects.filter(is_active=True).order_by("name"))
    return render(request, "public/booking.html", {
        "clinic": clinic, "site": site, "doctors": doctors, "services": services,
    })


def public_slots(request):
    """Свободные часовые слоты врача на дату (JSON)."""
    from django.http import JsonResponse
    from django.utils import timezone
    from datetime import datetime
    clinic, site = _ctx(request)
    doctor_id = request.GET.get("doctor")
    date_str = request.GET.get("date")
    if not doctor_id or not date_str:
        return JsonResponse({"slots": []})
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"slots": []})
    from apps.appointments.models import Appointment
    taken = set()
    for a in (Appointment.all_objects.filter(clinic=clinic, doctor_id=doctor_id, start_at__date=d)
              .exclude(status__in=["cancelled", "no_show"])):
        taken.add(timezone.localtime(a.start_at).hour)
    now = timezone.localtime()
    slots = []
    for h in range(WORK_START, WORK_END):
        if h in taken:
            continue
        if d == now.date() and h <= now.hour:
            continue
        slots.append("%02d:00" % h)
    return JsonResponse({"slots": slots})


def public_book_submit(request):
    """Создать заявку с сайта → серая запись в расписании + уведомление администраторам."""
    from django.http import JsonResponse
    from django.utils import timezone
    from django.db.models import Q
    from datetime import datetime, timedelta, time as dtime
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST"}, status=405)
    clinic, site = _ctx(request)
    name = (request.POST.get("name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    doctor_id = request.POST.get("doctor")
    date_str = request.POST.get("date")
    slot = request.POST.get("slot") or ""
    service_id = request.POST.get("service") or None
    if not (name and phone and doctor_id and date_str and slot):
        return JsonResponse({"ok": False, "error": "Заполните все поля"}, status=400)

    from apps.users.models import clinic_doctors, Branch, User, Role
    from apps.appointments.models import Appointment
    from apps.patients.models import Patient

    if not clinic_doctors(clinic).filter(pk=doctor_id).exists():
        return JsonResponse({"ok": False, "error": "Врач не найден"}, status=400)
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        hh = int(slot.split(":")[0])
    except (ValueError, IndexError):
        return JsonResponse({"ok": False, "error": "Неверная дата/время"}, status=400)

    start = timezone.make_aware(datetime.combine(d, dtime(hour=hh)))
    end = start + timedelta(hours=SLOT_HOURS)
    clash = (Appointment.all_objects.filter(clinic=clinic, doctor_id=doctor_id,
             start_at__lt=end, end_at__gt=start).exclude(status__in=["cancelled", "no_show"]).exists())
    if clash:
        return JsonResponse({"ok": False, "error": "Это время уже занято, выберите другое"}, status=409)

    branch = Branch.objects.filter(is_main=True).first() or Branch.objects.first()
    if branch is None:
        return JsonResponse({"ok": False, "error": "Нет филиала"}, status=400)

    patient = Patient.all_objects.filter(clinic=clinic, phone=phone, is_deleted=False).first()
    if patient is None:
        parts = name.split(None, 1)
        patient = Patient(first_name=parts[0], last_name=parts[1] if len(parts) > 1 else "",
                          phone=phone, branch=branch)
        patient.save()

    note = "Заявка с сайта"
    if name and patient.full_name.strip().lower() != name.strip().lower():
        note += " (на сайте указано имя: %s)" % name
    appt = Appointment(patient=patient, doctor_id=doctor_id, branch=branch,
                       start_at=start, end_at=end, status=Appointment.STATUS_SCHEDULED,
                       source="online", notes=note)
    if service_id:
        appt.service_id = service_id
    appt.save()
    if service_id:
        appt.services.add(service_id)

    try:
        from apps.notifications.models import Notification
        admins = (User.objects.filter(clinic=clinic, is_active=True)
                  .filter(Q(role__name__in=[Role.ADMIN, Role.ADMIN_MAIN])
                          | Q(roles__name__in=[Role.ADMIN, Role.ADMIN_MAIN])).distinct())
        for u in admins:
            Notification.send(u, "Новая заявка с сайта",
                              "%s, %s — %s %s" % (patient.full_name, phone, d.strftime("%d.%m.%Y"), slot),
                              type="appointment", link="/calendar/")
    except Exception:
        pass

    # WhatsApp (Green-API) — пациенту и врачу. Имя берём из карточки пациента (как в расписании).
    try:
        from apps.notifications.whatsapp import wa_send_text
        from django.conf import settings as dj_settings
        d_str, doc = d.strftime("%d.%m.%Y"), User.objects.filter(pk=doctor_id).first()
        doc_name = doc.name if doc else "—"
        wa_send_text(phone,
            "🦷 *%s*\n\n"
            "Здравствуйте, *%s*! 👋\n"
            "Ваша заявка на приём принята ✅\n\n"
            "📅 Дата: *%s*\n"
            "🕐 Время: *%s*\n"
            "👨‍⚕️ Врач: _%s_\n\n"
            "Мы свяжемся с вами для подтверждения. Спасибо, что выбрали нас! 💙"
            % (clinic.name, patient.first_name or patient.full_name, d_str, slot, doc_name))
        if doc and doc.phone:
            link = "https://%s/appointments/?focus=%s" % (
                getattr(dj_settings, "APP_HOST", "app.denta.tw1.ru"), appt.pk)
            wa_send_text(doc.phone,
                "🔔 *Новая заявка с сайта*\n\n"
                "👤 Пациент: *%s*\n"
                "📞 Телефон: %s\n"
                "📅 *%s*  🕐 *%s*\n\n"
                "🔗 Открыть запись:\n%s"
                % (patient.full_name, phone, d_str, slot, link))
        # WhatsApp-группы клиники
        from apps.notifications.whatsapp import notify_groups
        notify_groups(
            "🔔 *Новая заявка с сайта* — %s\n\n"
            "👤 Пациент: *%s*\n📞 %s\n📅 *%s*  🕐 *%s*\n👨‍⚕️ Врач: _%s_"
            % (clinic.name, patient.full_name, phone, d_str, slot, doc_name),
            clinic=clinic)
    except Exception:
        pass

    return JsonResponse({"ok": True})
