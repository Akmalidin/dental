"""Страница «Лист ожидания» (новый интерфейс) и её действия.
Логика подбора/записи/предложения — apps.appointments.waitlist."""
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import waitlist as wl
from .models import Appointment, WaitlistEntry


def _clinic(request):
    from apps.tenancy import get_current_clinic
    return get_current_clinic() or getattr(request.user, "clinic", None)


def _staff_doctor(pk):
    """Врач только текущей клиники."""
    from apps.users.models import User
    clinic = None
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    qs = User.objects.filter(pk=pk, is_active=True)
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    return qs.first()


def _entry_json(e):
    p = e.patient
    return {
        "id": e.pk, "patientId": p.pk, "patient": p.full_name, "phone": p.phone or "",
        "doctorId": e.doctor_id, "doctor": e.doctor.name if e.doctor_id else "",
        "serviceId": e.service_id, "service": e.service.name if e.service_id else "",
        "branchId": e.branch_id, "branch": e.branch.name if e.branch_id else "",
        "dateFrom": e.date_from.isoformat() if e.date_from else "",
        "dateTo": e.date_to.isoformat() if e.date_to else "",
        "part": e.part_of_day, "partLabel": e.get_part_of_day_display(),
        "duration": e.duration_min, "urgent": e.urgent, "note": e.note,
        "status": e.status, "statusLabel": e.get_status_display(),
        "offeredStart": (timezone.localtime(e.offered_start).strftime("%d.%m %H:%M") if e.offered_start else ""),
        "created": timezone.localtime(e.created_at).strftime("%d.%m.%Y"),
        "waitDays": (timezone.now() - e.created_at).days,
        "appointmentId": e.appointment_id,
    }


def waitlist_data(request):
    from apps.services.models import Service
    from apps.users.models import Branch, clinic_doctors
    clinic = _clinic(request)
    entries = (WaitlistEntry.objects.filter(status__in=wl.ACTIVE)
               .select_related("patient", "doctor", "service", "branch"))
    done = (WaitlistEntry.objects.exclude(status__in=wl.ACTIVE)
            .select_related("patient", "doctor", "service", "branch").order_by("-updated_at")[:30])
    slots = []
    if clinic is not None:
        for a in wl.free_slots(clinic.pk):
            m = wl.match(clinic.pk, a.doctor_id, a.branch_id, a.start_at, a.end_at)
            if not m:
                continue
            ls, le = timezone.localtime(a.start_at), timezone.localtime(a.end_at)
            slots.append({
                "start": a.start_at.isoformat(), "end": a.end_at.isoformat(),
                "label": f"{ls:%d.%m} {ls:%H:%M}–{le:%H:%M}",
                "doctorId": a.doctor_id, "doctor": a.doctor.name, "branchId": a.branch_id,
                "branch": a.branch.name if a.branch_id else "",
                "matches": [e.pk for e in m],
            })
    return {
        "entries": [_entry_json(e) for e in entries],
        "history": [_entry_json(e) for e in done],
        "slots": slots,
        "doctors": [{"id": d.pk, "name": d.name} for d in clinic_doctors(clinic)],
        "services": [{"id": s.pk, "name": s.name, "duration": s.duration or 30}
                     for s in Service.objects.filter(is_active=True).order_by("name")[:500]],
        "branches": [{"id": b.pk, "name": b.name} for b in Branch.objects.filter(is_active=True)],
        "today": timezone.localdate().isoformat(),
    }


@login_required
def newui_waitlist(request):
    from apps.users.newui_views import _render
    return _render(request, "waitlist", "waitlist.html", {"waitlist": waitlist_data(request)})


@login_required
def waitlist_json(request):
    return JsonResponse(waitlist_data(request))


@login_required
def waitlist_patients(request):
    """Поиск пациента для формы (имя/телефон), только своей клиники."""
    from apps.patients.models import Patient
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    digits = "".join(ch for ch in q if ch.isdigit())
    cond = Q(last_name__icontains=q) | Q(first_name__icontains=q) | Q(middle_name__icontains=q)
    if len(digits) >= 3:
        cond |= Q(phone__icontains=digits) | Q(phone_norm__icontains=digits)
    parts = q.split()
    if len(parts) >= 2:
        cond |= Q(last_name__icontains=parts[0], first_name__icontains=parts[1]) | \
            Q(first_name__icontains=parts[0], last_name__icontains=parts[1])
    rows = Patient.objects.filter(cond).order_by("last_name", "first_name")[:20]
    return JsonResponse({"results": [{"id": p.pk, "name": p.full_name, "phone": p.phone or ""} for p in rows]})


def _date(v):
    try:
        return datetime.fromisoformat(v).date() if v else None
    except ValueError:
        return None


@login_required
@require_POST
def waitlist_add(request):
    from apps.patients.models import Patient
    from apps.services.models import Service
    from apps.users.models import Branch
    P = request.POST
    patient = Patient.objects.filter(pk=P.get("patient_id") or 0).first()
    if patient is None:
        return JsonResponse({"ok": False, "error": "Выберите пациента"}, status=400)
    doctor = _staff_doctor(P.get("doctor_id")) if P.get("doctor_id") else None
    if P.get("doctor_id") and doctor is None:
        return JsonResponse({"ok": False, "error": "Врач не найден"}, status=400)
    service = Service.objects.filter(pk=P.get("service_id")).first() if P.get("service_id") else None
    branch = Branch.objects.filter(pk=P.get("branch_id")).first() if P.get("branch_id") else None
    d_from, d_to = _date(P.get("date_from")), _date(P.get("date_to"))
    if d_from and d_to and d_from > d_to:
        d_from, d_to = d_to, d_from
    part = P.get("part") if P.get("part") in dict(WaitlistEntry.PART_CHOICES) else WaitlistEntry.PART_ANY
    try:
        duration = max(10, min(480, int(P.get("duration") or 30)))
    except ValueError:
        duration = 30
    if WaitlistEntry.objects.filter(patient=patient, status__in=wl.ACTIVE,
                                    doctor=doctor).exists():
        return JsonResponse({"ok": False, "error": "Пациент уже в листе ожидания к этому врачу"}, status=400)
    e = WaitlistEntry.objects.create(
        patient=patient, doctor=doctor, service=service, branch=branch, date_from=d_from, date_to=d_to,
        part_of_day=part, duration_min=duration, urgent=P.get("urgent") in ("1", "true", "on"),
        note=(P.get("note") or "").strip()[:500], created_by=request.user,
    )
    return JsonResponse({"ok": True, "id": e.pk})


def _entry(pk):
    return WaitlistEntry.objects.select_related("patient", "doctor", "service").filter(pk=pk).first()


def _slot(request, entry):
    """Окно из запроса: start (ISO), doctor_id (или врач записи), длительность —
    из записи листа, но не дольше, чем end (если передан)."""
    try:
        start = datetime.fromisoformat(request.POST.get("start", ""))
    except ValueError:
        return None
    if timezone.is_naive(start):
        start = timezone.make_aware(start)
    doctor = _staff_doctor(request.POST.get("doctor_id") or entry.doctor_id or 0)
    if doctor is None:
        return None
    end = start + timedelta(minutes=entry.duration_min or 30)
    try:
        end_req = datetime.fromisoformat(request.POST.get("end", ""))
        if timezone.is_naive(end_req):
            end_req = timezone.make_aware(end_req)
        if end_req > start:
            end = min(end, end_req)
    except ValueError:
        pass
    return start, end, doctor


@login_required
@require_POST
def waitlist_book(request, pk):
    from apps.users.models import Branch
    e = _entry(pk)
    if e is None or e.status not in wl.ACTIVE:
        return JsonResponse({"ok": False, "error": "Запись листа не найдена"}, status=404)
    slot = _slot(request, e)
    if slot is None:
        return JsonResponse({"ok": False, "error": "Не указано время или врач"}, status=400)
    start, end, doctor = slot
    branch = (Branch.objects.filter(pk=request.POST.get("branch_id")).first() if request.POST.get("branch_id")
              else None) or e.branch or Branch.objects.filter(is_active=True).order_by("-is_main").first()
    if branch is None:
        return JsonResponse({"ok": False, "error": "Нет филиала"}, status=400)
    appt, err = wl.book(e, start, end, doctor, branch, request.user)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    return JsonResponse({"ok": True, "appointmentId": appt.pk})


@login_required
@require_POST
def waitlist_offer(request, pk):
    e = _entry(pk)
    if e is None or e.status not in wl.ACTIVE:
        return JsonResponse({"ok": False, "error": "Запись листа не найдена"}, status=404)
    slot = _slot(request, e)
    if slot is None:
        return JsonResponse({"ok": False, "error": "Не указано время или врач"}, status=400)
    start, _end, doctor = slot
    if not wl.offer(e, start, doctor):
        return JsonResponse({"ok": False, "error": "Не удалось отправить сообщение (нет WhatsApp/Telegram у пациента?)"},
                            status=400)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def waitlist_status(request, pk):
    e = _entry(pk)
    st = request.POST.get("status")
    if e is None or st not in dict(WaitlistEntry.STATUS_CHOICES):
        return JsonResponse({"ok": False}, status=404)
    e.status = st
    e.save(update_fields=["status", "updated_at"])
    return JsonResponse({"ok": True})


def active_count(clinic):
    if clinic is None:
        return 0
    return WaitlistEntry.all_clinics.filter(clinic=clinic, status__in=wl.ACTIVE).count()
