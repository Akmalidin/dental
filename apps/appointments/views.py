import json
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import Appointment, Cabinet
from .forms import AppointmentForm


@login_required
def calendar_view(request):
    """Calendar page with booking modal."""
    User = request.user.__class__
    doctors = User.objects.filter(role__name="doctor", is_active=True).select_related("role")
    branches = request.user.branches.all()
    from apps.patients.models import Patient
    from apps.services.models import Service
    patients = Patient.objects.order_by("last_name").values("id", "first_name", "last_name", "phone")
    services = Service.objects.filter(is_active=True).values("id", "name", "price", "duration")
    return render(request, "appointments/calendar.html", {
        "doctors": doctors,
        "branches": branches,
        "all_services": Service.objects.filter(is_active=True).order_by("name"),
        "patients_json": [
            {"id": p["id"], "name": f'{p["last_name"]} {p["first_name"]}', "phone": p["phone"]}
            for p in patients
        ],
        "services_json": [
            {"id": s["id"], "name": s["name"], "price": float(s["price"]), "duration": s["duration"]}
            for s in services
        ],
    })


@login_required
@require_POST
def appointment_create_quick(request):
    """AJAX: create appointment from calendar modal."""
    from apps.patients.models import Patient
    from apps.services.models import Service
    from apps.users.models import Branch
    try:
        from django.utils import timezone as _tz
        data = json.loads(request.body)
        User = request.user.__class__
        doctor = User.objects.get(pk=data["doctor_id"])
        start = datetime.fromisoformat(data["start_at"])
        if _tz.is_naive(start):
            start = _tz.make_aware(start)
        # Support multiple services (service_ids list) or single (service_id)
        service_ids = data.get("service_ids") or ([data["service_id"]] if data.get("service_id") else [])
        services = list(Service.objects.filter(pk__in=service_ids)) if service_ids else []
        service = services[0] if services else None
        if not service:
            service, _ = Service.objects.get_or_create(
                name="Визит к врачу", defaults={"price": 0, "duration": 30, "is_active": True}
            )
            services = [service]
        duration = sum(s.duration for s in services) or 30
        end = start + timedelta(minutes=int(data.get("duration") or duration))

        # Prevent double-booking: doctor can't have overlapping appointments
        overlap = Appointment.objects.filter(
            doctor=doctor, start_at__lt=end, end_at__gt=start,
        ).exclude(status=Appointment.STATUS_CANCELLED).first()
        if overlap:
            return JsonResponse({
                "error": "У врача уже есть запись на это время (%s–%s). Выберите другое время." % (
                    overlap.start_at.strftime("%H:%M"), overlap.end_at.strftime("%H:%M"))
            }, status=400)

        branch = doctor.branches.first() or Branch.objects.first()
        appt = Appointment.objects.create(
            patient=Patient.objects.filter(pk=data.get("patient_id")).first(),
            doctor=doctor,
            branch=branch,
            service=service,
            start_at=start,
            end_at=end,
            status=data.get("status", Appointment.STATUS_SCHEDULED),
            notes=data.get("notes", ""),
            created_by=request.user,
        )
        if services:
            appt.services.set(services)
        return JsonResponse({"ok": True, "id": appt.pk})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def appointment_list(request):
    from .models import CancellationReason
    # Lazy-seed default cancellation reasons on first use
    if not CancellationReason.objects.exists():
        for i, name in enumerate([
            "Клиент не пришёл", "Клиент попросил отменить",
            "Перенос на другую дату", "Заболел врач", "Другая причина",
        ]):
            CancellationReason.objects.create(name=name, sort_order=i)

    qs = Appointment.objects.select_related(
        "patient", "doctor", "branch", "cabinet", "service", "cancellation_reason"
    ).order_by("-start_at")
    if request.user.is_doctor:
        qs = qs.filter(doctor=request.user)
    current_status = request.GET.get("status", "")
    if current_status:
        qs = qs.filter(status=current_status)
    form = AppointmentForm(initial={"doctor": request.user if request.user.is_doctor else None})
    return render(request, "appointments/list.html", {
        "appointments": qs,
        "current_status": current_status,
        "form": form,
        "cancel_reasons": CancellationReason.objects.filter(is_active=True),
    })


@login_required
def appointment_create(request):
    form = AppointmentForm(request.POST or None, initial={
        "doctor": request.user if request.user.is_doctor else None,
        "created_by": request.user,
    })
    if form.is_valid():
        appt = form.save(commit=False)
        appt.created_by = request.user
        if not appt.service_id:
            from apps.services.models import Service
            appt.service, _ = Service.objects.get_or_create(
                name="Визит к врачу", defaults={"price": 0, "duration": 30, "is_active": True}
            )
        appt.save()
        messages.success(request, _("Запись добавлена"))
        return redirect("appointment_list")
    return render(request, "appointments/form.html", {"form": form})


@login_required
def appointment_edit(request, pk):
    appt = get_object_or_404(Appointment, pk=pk)
    form = AppointmentForm(request.POST or None, instance=appt)
    if form.is_valid():
        form.save()
        messages.success(request, _("Запись обновлена"))
        return redirect("appointment_list")
    return render(request, "appointments/form.html", {"form": form, "object": appt})


@login_required
@require_POST
def appointment_move(request, pk):
    """AJAX: drag/resize an appointment on the calendar (update start/end)."""
    from django.utils import timezone as _tz
    appt = get_object_or_404(Appointment, pk=pk)
    try:
        data = json.loads(request.body)
        start = datetime.fromisoformat(data["start"])
        end = datetime.fromisoformat(data["end"])
        if _tz.is_naive(start):
            start = _tz.make_aware(start)
        if _tz.is_naive(end):
            end = _tz.make_aware(end)
        overlap = Appointment.objects.filter(
            doctor=appt.doctor, start_at__lt=end, end_at__gt=start,
        ).exclude(pk=pk).exclude(status=Appointment.STATUS_CANCELLED).exists()
        if overlap:
            return JsonResponse({"error": "Пересечение с другой записью этого врача"}, status=400)
        appt.start_at = start
        appt.end_at = end
        appt.save(update_fields=["start_at", "end_at"])
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def appointment_status(request, pk):
    from .models import CancellationReason
    appt = get_object_or_404(Appointment, pk=pk)
    new_status = request.POST.get("status")
    if new_status in dict(Appointment.STATUS_CHOICES):
        appt.status = new_status
        if new_status == Appointment.STATUS_CANCELLED:
            reason_id = request.POST.get("cancellation_reason")
            appt.cancellation_reason = CancellationReason.objects.filter(pk=reason_id).first() if reason_id else None
            appt.cancel_note = request.POST.get("cancel_note", "")[:300]
            appt.save(update_fields=["status", "cancellation_reason", "cancel_note"])
        else:
            appt.save(update_fields=["status"])
        messages.success(request, _("Статус записи изменён"))
    return redirect("appointment_list")


@login_required
def appointment_delete(request, pk):
    appt = get_object_or_404(Appointment, pk=pk)
    if request.method == "POST":
        appt.status = Appointment.STATUS_CANCELLED
        appt.save()
        messages.success(request, _("Запись отменена"))
        return redirect("appointment_list")
    return render(request, "appointments/confirm_delete.html", {"object": appt})
