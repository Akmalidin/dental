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


def schedule_violation(doctor, start, end):
    """Проверка, что приём укладывается в график работы врача.

    Возвращает строку-ошибку, либо None, если всё в порядке.
    Если у врача вообще нет настроенного графика — не ограничиваем (None),
    чтобы не блокировать клиники, которые график не ведут.
    """
    from django.utils import timezone as _tz
    from apps.users.models_salary import DoctorSchedule

    if not doctor:
        return None
    # Если у врача нет ни одной записи в графике — ограничения не применяем.
    if not DoctorSchedule.objects.filter(doctor=doctor).exists():
        return None

    local_start = _tz.localtime(start)
    local_end = _tz.localtime(end)
    dow = local_start.weekday()  # 0=Пн … 6=Вс — совпадает с DoctorSchedule.day_of_week

    sched = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=dow).first()
    if not sched or not sched.is_working:
        return "Врач не работает в этот день. Запись возможна только в рабочие дни по графику."

    if local_start.time() < sched.start_time or local_end.time() > sched.end_time:
        return "Время вне графика работы врача (%s–%s). Выберите время в рабочих часах." % (
            sched.start_time.strftime("%H:%M"), sched.end_time.strftime("%H:%M"))
    return None


def notify_appointment_cancelled(appt):
    """Уведомить об отмене записи: пациента, врача и WhatsApp-группы клиники.
    Безопасно: при выключенном WhatsApp/ошибках ничего не падает."""
    try:
        from apps.notifications.whatsapp import wa_send_text, notify_groups, wa_enabled
        from apps.settings_clinic.models import ClinicSettings
        from django.utils import timezone as _tz
        if not wa_enabled():
            return
        st = _tz.localtime(appt.start_at)
        clinic_name = ClinicSettings.get().name
        doctor_name = appt.doctor.name if appt.doctor else "—"
        pname = (appt.patient.first_name or appt.patient.full_name) if appt.patient_id else ""
        date_s, time_s = st.strftime("%d.%m.%Y"), st.strftime("%H:%M")
        # пациенту
        if appt.patient_id and appt.patient.phone:
            wa_send_text(appt.patient.phone,
                         "❌ *%s*\n\nЗдравствуйте, *%s*!\n"
                         "Ваша запись *отменена*.\n\n"
                         "📅 Дата: *%s*\n🕐 Время: *%s*\n👨‍⚕️ Врач: _%s_\n\n"
                         "Чтобы записаться повторно — позвоните нам или оставьте заявку на сайте."
                         % (clinic_name, pname, date_s, time_s, doctor_name))
        # врачу
        if appt.doctor_id and getattr(appt.doctor, "phone", ""):
            wa_send_text(appt.doctor.phone,
                         "❌ *Отмена записи*\n\n"
                         "Пациент: *%s*\n📅 %s 🕐 %s\n👨‍⚕️ Врач: _%s_"
                         % (appt.patient.full_name if appt.patient_id else "—",
                            date_s, time_s, doctor_name))
        # группы клиники
        notify_groups(
            "❌ *Отмена записи* — %s\n\nПациент: *%s*\n📅 %s 🕐 %s\n👨‍⚕️ Врач: _%s_"
            % (clinic_name, appt.patient.full_name if appt.patient_id else "—",
               date_s, time_s, doctor_name),
            clinic=appt.clinic,
        )
    except Exception:
        pass


def doctor_schedules_map(doctors):
    """{doctor_id: {day_of_week: [HH:MM, HH:MM] | null}} — для подсказок в календаре."""
    from apps.users.models_salary import DoctorSchedule
    out = {}
    doctor_ids = [d.pk for d in doctors]
    for s in DoctorSchedule.objects.filter(doctor_id__in=doctor_ids):
        day = out.setdefault(s.doctor_id, {})
        day[s.day_of_week] = ([s.start_time.strftime("%H:%M"), s.end_time.strftime("%H:%M")]
                              if s.is_working else None)
    return out


@login_required
def calendar_view(request):
    """Calendar page with booking modal."""
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic
    doctors = clinic_doctors(get_current_clinic())
    # врач без права «видеть всех» — фильтр в календаре предзаполняется собой
    default_doctor = (request.user.pk if (request.user.is_doctor and not request.user.is_admin
                                          and not request.user.can_view_all_appointments) else "")
    branches = request.user.branches.all()
    from apps.patients.models import Patient
    from apps.services.models import Service
    patients = Patient.objects.order_by("last_name").values("id", "first_name", "last_name", "phone")
    services = Service.objects.filter(is_active=True).values("id", "name", "price", "duration")
    return render(request, "appointments/calendar.html", {
        "doctors": doctors,
        "default_doctor": default_doctor,
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
        "schedules_json": doctor_schedules_map(doctors),
    })


@login_required
def appointment_day_grid(request):
    """Кастомный посуточный вид с колонками по врачам (без FullCalendar Premium)."""
    from datetime import datetime, date, time, timedelta
    from django.utils import timezone
    User = request.user.__class__

    # дата
    qd = request.GET.get("date")
    try:
        day = datetime.strptime(qd, "%Y-%m-%d").date() if qd else timezone.localdate()
    except ValueError:
        day = timezone.localdate()

    DAY_START, DAY_END = 8, 21          # рабочее окно 08:00–21:00
    PX_PER_MIN = 1.0                    # масштаб
    total_min = (DAY_END - DAY_START) * 60
    hours = list(range(DAY_START, DAY_END + 1))

    STATUS_COLORS = {
        "scheduled": "#6366F1", "confirmed": "#6366F1",
        "arrived": "#F59E0B", "in_progress": "#F59E0B",
        "completed": "#22C55E", "no_show": "#EF4444", "cancelled": "#EF4444",
    }

    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic
    doctors = list(clinic_doctors(get_current_clinic()))
    start_dt = timezone.make_aware(datetime.combine(day, time(0, 0)))
    end_dt = start_dt + timedelta(days=1)
    appts = (Appointment.objects.filter(start_at__gte=start_dt, start_at__lt=end_dt)
             .select_related("patient", "doctor", "service")
             .prefetch_related("services"))

    by_doctor = {d.pk: [] for d in doctors}
    unassigned = []
    for a in appts:
        local_start = timezone.localtime(a.start_at)
        local_end = timezone.localtime(a.end_at)
        start_min = (local_start.hour - DAY_START) * 60 + local_start.minute
        dur = max(15, int((local_end - local_start).total_seconds() // 60))
        top = max(0, start_min) * PX_PER_MIN
        height = min(dur, total_min - start_min) * PX_PER_MIN
        services = ", ".join(s.name for s in a.services.all()) or (a.service.name if a.service else "—")
        block = {
            "id": a.pk, "top": int(round(top)), "height": int(round(max(height, 18))),
            "color": STATUS_COLORS.get(a.status, "#6366F1"),
            "cancelled": a.status == "cancelled",
            "time": f"{local_start:%H:%M}–{local_end:%H:%M}",
            "patient": a.patient.full_name if a.patient else "—",
            "services": services, "status_display": a.get_status_display(),
        }
        (by_doctor.get(a.doctor_id, unassigned)).append(block)

    columns = [{"doctor": d, "blocks": by_doctor.get(d.pk, [])} for d in doctors]
    if unassigned:
        columns.append({"doctor": None, "blocks": unassigned})

    # позиция для авто-скролла: к первой записи дня (или 9:00)
    all_tops = [b["top"] for col in columns for b in col["blocks"]]
    scroll_to = max(0, (min(all_tops) - 30)) if all_tops else (9 - DAY_START) * 60

    return render(request, "appointments/day_grid.html", {
        "day": day,
        "prev_day": (day - timedelta(days=1)).isoformat(),
        "next_day": (day + timedelta(days=1)).isoformat(),
        "today": timezone.localdate().isoformat(),
        "hours": [{"h": h, "top": int((h - DAY_START) * 60 * PX_PER_MIN)} for h in hours],
        "grid_height": int(total_min * PX_PER_MIN),
        "columns": columns,
        "day_start": DAY_START,
        "scroll_to": int(scroll_to),
    })


@login_required
def schedule_print(request):
    """Печать расписания на диапазон дат (день/неделя/месяц), опц. один врач (?doctor=id).
    Параметры: from, to (YYYY-MM-DD) — диапазон; или date — один день."""
    from datetime import datetime, time, timedelta
    from collections import OrderedDict
    from django.utils import timezone

    def parse(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    today = timezone.localdate()
    d_from = parse(request.GET.get("from")) or parse(request.GET.get("date")) or today
    d_to = parse(request.GET.get("to")) or parse(request.GET.get("date")) or d_from
    if d_to < d_from:
        d_from, d_to = d_to, d_from
    if (d_to - d_from).days > 62:
        d_to = d_from + timedelta(days=62)
    doctor_id = request.GET.get("doctor")

    start_dt = timezone.make_aware(datetime.combine(d_from, time(0, 0)))
    end_dt = timezone.make_aware(datetime.combine(d_to, time(0, 0))) + timedelta(days=1)
    qs = (Appointment.objects.filter(start_at__gte=start_dt, start_at__lt=end_dt)
          .exclude(status="cancelled")
          .select_related("patient", "doctor", "service").prefetch_related("services")
          .order_by("start_at"))
    if doctor_id:
        qs = qs.filter(doctor_id=doctor_id)

    days = OrderedDict()
    cur = d_from
    while cur <= d_to:
        days[cur] = []
        cur += timedelta(days=1)
    for a in qs:
        ld = timezone.localtime(a.start_at).date()
        if ld in days:
            days[ld].append(a)

    multi = d_from != d_to
    day_list = [{"date": dt, "appts": ap} for dt, ap in days.items() if ap or not multi]

    doctor_name = ""
    if doctor_id:
        from apps.users.models import User
        u = User.objects.filter(pk=doctor_id).first()
        doctor_name = u.name if u else ""
    from apps.settings_clinic.models import ClinicSettings
    return render(request, "appointments/schedule_print.html", {
        "day_list": day_list, "clinic_settings": ClinicSettings.get(),
        "d_from": d_from, "d_to": d_to, "multi": multi, "doctor_name": doctor_name,
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
        ).exclude(status__in=[Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW]).first()
        if overlap:
            return JsonResponse({
                "error": "У врача уже есть запись на это время (%s–%s). Выберите другое время." % (
                    overlap.start_at.strftime("%H:%M"), overlap.end_at.strftime("%H:%M"))
            }, status=400)

        sched_err = schedule_violation(doctor, start, end)
        if sched_err:
            return JsonResponse({"error": sched_err}, status=400)

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
    from .api_views import apply_appt_visibility
    qs = apply_appt_visibility(qs, request.user, request.GET.get("doctor"))
    current_status = request.GET.get("status", "")
    if current_status:
        qs = qs.filter(status=current_status)
    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q)
            | Q(patient__phone__icontains=q) | Q(doctor__name__icontains=q)
            | Q(service__name__icontains=q)
        )
    form = AppointmentForm(initial={"doctor": request.user if request.user.is_doctor else None})

    # Прошедшие записи без отметки исхода — «требуют внимания»
    from django.utils import timezone
    stale = (Appointment.objects.select_related("patient", "doctor")
             .filter(status__in=["scheduled", "confirmed"], end_at__lt=timezone.now())
             .order_by("start_at"))
    stale = apply_appt_visibility(stale, request.user, None)
    stale_count = stale.count()

    return render(request, "appointments/list.html", {
        "appointments": qs,
        "current_status": current_status,
        "q": q,
        "form": form,
        "cancel_reasons": CancellationReason.objects.filter(is_active=True),
        "stale_appointments": stale[:100],
        "stale_count": stale_count,
    })


@login_required
def appointment_create(request):
    # предзаполнение из посуточной сетки: ?date=&time=&doctor=
    initial = {
        "doctor": request.user if request.user.is_doctor else None,
        "created_by": request.user,
    }
    gd, gt, gdoc = request.GET.get("date"), request.GET.get("time"), request.GET.get("doctor")
    if gd and gt:
        from datetime import datetime, timedelta
        try:
            start = datetime.strptime(f"{gd} {gt}", "%Y-%m-%d %H:%M")
            initial["start_at"] = start
            initial["end_at"] = start + timedelta(minutes=30)
        except ValueError:
            pass
    if gdoc:
        initial["doctor"] = gdoc
    form = AppointmentForm(request.POST or None, initial=initial)
    if form.is_valid():
        appt = form.save(commit=False)
        appt.created_by = request.user
        if not appt.status:
            appt.status = Appointment.STATUS_SCHEDULED
        if not appt.branch_id:   # по умолчанию активный/основной филиал
            from apps.users.models import Branch
            appt.branch = (Branch.objects.filter(pk=request.session.get("active_branch")).first()
                           or Branch.objects.filter(is_main=True).first()
                           or request.user.branches.first() or Branch.objects.first())
        if not appt.service_id:
            from apps.services.models import Service
            appt.service, _created = Service.objects.get_or_create(
                name="Визит к врачу", defaults={"price": 0, "duration": 30, "is_active": True}
            )
        appt.save()
        form.save_m2m()
        try:
            from apps.notifications.models import Notification
            from django.utils import timezone as _tz2
            pname = appt.patient.full_name if appt.patient else "Пациент"
            Notification.send(appt.doctor, "Новая запись на приём",
                              f"{pname} — {_tz2.localtime(appt.start_at):%d.%m %H:%M}",
                              type="appointment", link="/appointments/", actor=request.user)
        except Exception:
            pass
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
        ).exclude(pk=pk).exclude(status__in=[Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW]).exists()
        if overlap:
            return JsonResponse({"error": "Пересечение с другой записью этого врача"}, status=400)
        sched_err = schedule_violation(appt.doctor, start, end)
        if sched_err:
            return JsonResponse({"error": sched_err}, status=400)
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
            notify_appointment_cancelled(appt)
        else:
            appt.save(update_fields=["status"])
        messages.success(request, _("Статус записи изменён"))
        # WhatsApp пациенту при подтверждении приёма (Green-API; если включено в env)
        if (new_status == Appointment.STATUS_CONFIRMED
                and appt.patient_id and appt.patient.phone):
            try:
                from apps.notifications.whatsapp import wa_send_text
                from apps.settings_clinic.models import ClinicSettings
                from django.utils import timezone as _tz
                st = _tz.localtime(appt.start_at)
                wa_send_text(appt.patient.phone,
                             "✅ *%s*\n\n"
                             "Здравствуйте, *%s*!\n"
                             "Ваш приём *подтверждён* 🎉\n\n"
                             "📅 Дата: *%s*\n"
                             "🕐 Время: *%s*\n"
                             "👨‍⚕️ Врач: _%s_\n\n"
                             "Ждём вас! 💙 Если планы изменятся — позвоните нам."
                             % (ClinicSettings.get().name,
                                appt.patient.first_name or appt.patient.full_name,
                                st.strftime("%d.%m.%Y"), st.strftime("%H:%M"),
                                appt.doctor.name if appt.doctor else "—"))
            except Exception:
                pass
    return redirect("appointment_list")


@login_required
@require_POST
def appointment_finish(request, pk):
    """Завершить приём и/или назначить следующий.

    - complete=1   → текущая запись становится «Завершён»
    - next_date    → создать следующую запись (тот же пациент/врач/филиал, то же время дня)
    Сценарии: «Завершить приём» шлёт complete=1 (+ дата опционально);
    «Назначить след. приём» (уже завершённой) шлёт только next_date.
    """
    from django.http import JsonResponse
    from django.utils import timezone as _tz
    from datetime import datetime
    appt = get_object_or_404(Appointment, pk=pk)
    do_complete = request.POST.get("complete") == "1"
    next_date = (request.POST.get("next_date") or "").strip()

    new_id = None
    if next_date:
        if not appt.patient_id:
            return JsonResponse({"error": "У записи нет пациента"}, status=400)
        try:
            d = datetime.strptime(next_date, "%Y-%m-%d").date()
        except ValueError:
            return JsonResponse({"error": "Неверная дата"}, status=400)
        dur = appt.end_at - appt.start_at
        new_start = datetime.combine(d, _tz.localtime(appt.start_at).timetz())
        nxt = Appointment.objects.create(
            patient=appt.patient, doctor=appt.doctor, branch=appt.branch,
            start_at=new_start, end_at=new_start + dur,
            status=Appointment.STATUS_SCHEDULED,
        )
        new_id = nxt.pk

    if do_complete and appt.status not in ("cancelled", "completed"):
        appt.status = Appointment.STATUS_COMPLETED
        appt.save(update_fields=["status"])

    if request.POST.get("redirect"):
        messages.success(request, _("Приём завершён") if do_complete else _("Следующий приём назначен"))
        return redirect(request.META.get("HTTP_REFERER") or "appointment_list")
    return JsonResponse({"ok": True, "next_id": new_id, "status": appt.status})


@login_required
def appointment_delete(request, pk):
    appt = get_object_or_404(Appointment, pk=pk)
    if request.method == "POST":
        appt.status = Appointment.STATUS_CANCELLED
        appt.save()
        notify_appointment_cancelled(appt)
        messages.success(request, _("Запись отменена"))
        return redirect("appointment_list")
    return render(request, "appointments/confirm_delete.html", {"object": appt})


@login_required
def appointment_detail_json(request, pk):
    """Полные данные записи для модала в календаре."""
    from django.http import JsonResponse
    from django.utils import timezone as _tz
    appt = get_object_or_404(
        Appointment.objects.select_related("patient", "doctor", "cancellation_reason").prefetch_related("services"),
        pk=pk,
    )
    p = appt.patient
    start = _tz.localtime(appt.start_at)
    end = _tz.localtime(appt.end_at)
    dur_min = int((end - start).total_seconds() // 60)

    procedures = []
    treatment_id = None
    if p:
        from apps.treatments.models import Treatment
        last_t = (Treatment.objects.filter(patient=p).exclude(status="cancelled")
                  .order_by("-created_at").prefetch_related("cures__service", "cures__doctor").first())
        if last_t:
            treatment_id = last_t.pk
            paid = last_t.debt <= 0
            for c in last_t.cures.all():
                procedures.append({
                    "service": c.service.name if c.service else "—",
                    "tooth": c.tooth_number or "",
                    "doctor": c.doctor.name if c.doctor else "",
                    "price": float(c.price),
                    "paid": paid,
                })

    first_visit = False
    if p:
        from apps.treatments.models import Treatment
        first_visit = Treatment.objects.filter(patient=p).count() <= 1

    return JsonResponse({
        "ok": True,
        "appointment": {
            "id": appt.pk,
            "date": f"{start:%d.%m.%Y}",
            "time": f"{start:%H:%M} – {end:%H:%M}",
            "duration": f"{dur_min // 60}h {dur_min % 60}m",
            "doctor": appt.doctor.name if appt.doctor else "",
            "doctor_id": appt.doctor_id,
            "status": appt.status,
            "status_display": appt.get_status_display(),
            "source": appt.source,
            "notes": appt.notes or "",
            "cancelled": appt.status == "cancelled",
            "cancel_reason": appt.cancellation_reason.name if appt.cancellation_reason else "",
            "cancel_note": appt.cancel_note or "",
        },
        "patient": {
            "id": p.pk if p else None,
            "name": p.full_name if p else "Без пациента",
            "age": p.age if p else None,
            "phone": p.phone if p else "",
            "debt": float(p.debt) if p else 0,
            "first_visit": first_visit,
        },
        "treatment_id": treatment_id,
        "procedures": procedures,
    })


@login_required
@require_POST
def appointment_trash(request, pk):
    """Мягкое удаление записи (в корзину)."""
    appt = get_object_or_404(Appointment, pk=pk)
    appt.soft_delete(request.user)
    notify_appointment_cancelled(appt)
    messages.success(request, _("Запись перемещена в корзину"))
    return redirect("appointment_list")
