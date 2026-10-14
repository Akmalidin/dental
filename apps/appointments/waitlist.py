"""Лист ожидания: подбор пациентов под освободившееся окно, уведомление
администраторов, запись в окно и предложение времени пациенту.

Окно освобождается, когда будущую запись отменяют, удаляют или переносят
на другое время (см. signals в apps.appointments.apps). Тогда:
1. match() ищет подходящих пациентов из листа (врач — тот же или «любой»,
   филиал, даты, время дня, длительность влезает в окно; сначала срочные,
   потом — кто дольше ждёт);
2. если такие есть — администраторам клиники приходит уведомление со
   ссылкой на «Лист ожидания», где окно и подходящие пациенты уже показаны;
3. администратор жмёт «Записать» (book) или «Предложить» (offer — сообщение
   пациенту в WhatsApp/Telegram; ответ «Да» поймёт ИИ-ассистент: сообщение
   сохраняется в переписке).
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Appointment, WaitlistEntry

ACTIVE = (WaitlistEntry.STATUS_WAITING, WaitlistEntry.STATUS_OFFERED)
BUSY_EXCLUDE = (Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW)


def _part_ok(part, local_start):
    h = local_start.hour
    if part == WaitlistEntry.PART_MORNING:
        return h < 12
    if part == WaitlistEntry.PART_DAY:
        return 12 <= h < 16
    if part == WaitlistEntry.PART_EVENING:
        return h >= 16
    return True


def match(clinic_id, doctor_id, branch_id, start, end):
    """Подходящие записи листа ожидания для окна [start, end) у врача."""
    local = timezone.localtime(start)
    day = local.date()
    minutes = int((end - start).total_seconds() // 60)
    qs = (WaitlistEntry.all_clinics.filter(clinic_id=clinic_id, status__in=ACTIVE)
          .select_related("patient", "doctor", "service"))
    out = []
    for e in qs:
        if e.doctor_id and e.doctor_id != doctor_id:
            continue
        if e.branch_id and branch_id and e.branch_id != branch_id:
            continue
        if e.date_from and day < e.date_from:
            continue
        if e.date_to and day > e.date_to:
            continue
        if not _part_ok(e.part_of_day, local):
            continue
        if e.duration_min and e.duration_min > minutes:
            continue
        if e.patient is None or getattr(e.patient, "is_deleted", False):
            continue
        out.append(e)
    out.sort(key=lambda e: (not e.urgent, e.created_at))
    return out


def slot_is_free(doctor_id, start, end, exclude_pk=None):
    qs = Appointment.all_objects.filter(doctor_id=doctor_id, start_at__lt=end, end_at__gt=start,
                                        is_deleted=False).exclude(status__in=BUSY_EXCLUDE)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return not qs.exists()


def free_slots(clinic_id, days=14, limit=30):
    """Освободившиеся окна (отменённые/удалённые будущие записи, время которых
    до сих пор никем не занято) — для блока «Свободные окна» на странице."""
    now = timezone.now()
    seen, out = set(), []
    qs = (Appointment.all_objects.filter(clinic_id=clinic_id, start_at__gt=now,
                                         start_at__lt=now + timedelta(days=days))
          .filter(models_q_freed()).select_related("doctor", "branch").order_by("start_at"))
    for a in qs:
        key = (a.doctor_id, a.start_at, a.end_at)
        if key in seen or not slot_is_free(a.doctor_id, a.start_at, a.end_at):
            continue
        seen.add(key)
        out.append(a)
        if len(out) >= limit:
            break
    return out


def models_q_freed():
    from django.db.models import Q
    return Q(status=Appointment.STATUS_CANCELLED) | Q(is_deleted=True)


def notify_freed(clinic_id, doctor_id, branch_id, start, end):
    """Окно освободилось — если в листе есть подходящие, уведомить админов."""
    if start <= timezone.now() or not slot_is_free(doctor_id, start, end):
        return 0
    matches = match(clinic_id, doctor_id, branch_id, start, end)
    if not matches:
        return 0
    from apps.notifications.models import Notification
    from apps.users.models import Role, User
    doctor = User.objects.filter(pk=doctor_id).first()
    local = timezone.localtime(start)
    names = ", ".join(e.patient.full_name for e in matches[:3]) + ("…" if len(matches) > 3 else "")
    title = f"Освободилось окно {local:%d.%m %H:%M}" + (f" — {doctor.name}" if doctor else "")
    body = f"Лист ожидания: подходит {len(matches)} — {names}"
    recipients = (User.objects.filter(clinic_id=clinic_id, is_active=True)
                  .filter(role__name__in=[Role.ADMIN, Role.ADMIN_MAIN]))
    from apps.users.models import Clinic
    clinic = Clinic.objects.filter(pk=clinic_id).first()
    for u in recipients:
        try:
            Notification.send(u, title, body, type="appointment", link="/new/waitlist/", clinic=clinic)
        except Exception:  # noqa: BLE001
            pass
    return len(matches)


def on_appointment_freed(appt_pk, clinic_id, doctor_id, branch_id, start, end):
    transaction.on_commit(lambda: _safe(notify_freed, clinic_id, doctor_id, branch_id, start, end))


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("apps").exception("waitlist notify failed")


def upcoming_appointment(patient):
    """Ближайшая будущая запись пациента — её предлагаем перенести на
    освободившееся время вместо второй записи."""
    return (Appointment.objects.filter(patient=patient, start_at__gt=timezone.now(), is_deleted=False,
                                       status__in=(Appointment.STATUS_SCHEDULED, Appointment.STATUS_CONFIRMED))
            .select_related("doctor").order_by("start_at").first())


def book(entry, start, end, doctor, branch, user, move=None):
    """Записать пациента из листа в окно. move — его уже существующая будущая
    запись: она переносится на это время (без второй записи).
    Возвращает (appointment, ошибка)."""
    if start <= timezone.now():
        return None, "Это время уже прошло"
    if not slot_is_free(doctor.pk, start, end, exclude_pk=move.pk if move else None):
        return None, "Это время уже занято"
    with transaction.atomic():
        if move is not None:
            appt = move
            appt.start_at, appt.end_at, appt.doctor, appt.branch = start, end, doctor, branch
            appt.status = Appointment.STATUS_SCHEDULED
            appt.notes = ("Перенесено из листа ожидания. " + (appt.notes or "")).strip()
            appt.save(update_fields=["start_at", "end_at", "doctor", "branch", "status", "notes"])
        else:
            appt = Appointment.objects.create(
                clinic_id=entry.clinic_id, patient=entry.patient, doctor=doctor, branch=branch,
                service=entry.service, start_at=start, end_at=end, status=Appointment.STATUS_SCHEDULED,
                notes=("Из листа ожидания. " + entry.note).strip(), source="manual", created_by=user,
            )
            if entry.service_id:
                appt.services.add(entry.service)
        entry.status = WaitlistEntry.STATUS_BOOKED
        entry.appointment = appt
        entry.save(update_fields=["status", "appointment", "updated_at"])
    try:
        from .views import notify_appointment_created
        notify_appointment_created(appt, created_by=user)
    except Exception:  # noqa: BLE001
        pass
    return appt, None


def offer_text(entry, start, doctor):
    from apps.settings_clinic.models import ClinicSettings
    local = timezone.localtime(start)
    name = entry.patient.first_name or entry.patient.full_name
    return ("Здравствуйте, %s! Это %s.\n\nОсвободилось время у врача %s — *%s в %s*.\n"
            "Вы просили записать вас пораньше. Записать вас на это время? Ответьте «Да» или «Нет»."
            % (name, ClinicSettings.get().name, doctor.name, local.strftime("%d.%m"), local.strftime("%H:%M")))


def offer(entry, start, doctor):
    """Предложить пациенту окно сообщением (основной мессенджер клиники, при
    неудаче — второй). Сообщение сохраняется в переписке."""
    from apps.notifications.models import WaMessage
    from apps.notifications.whatsapp import wa_enabled, wa_send_text
    from apps.notifications.telegram import tg_enabled, tg_send_text
    from apps.settings_clinic.models import ClinicSettings
    p = entry.patient
    msg = offer_text(entry, start, doctor)

    def via_wa():
        if not (p.phone and wa_enabled()):
            return False
        ok = wa_send_text(p.phone, msg)
        WaMessage.objects.create(patient=p, direction="out", channel="wa", phone=p.phone, body=msg, ok=ok)
        return ok

    def via_tg():
        if not (p.telegram_chat_id and tg_enabled()):
            return False
        ok = tg_send_text(p.telegram_chat_id, msg.replace("*", ""))
        WaMessage.objects.create(patient=p, direction="out", channel="tg",
                                 phone=str(p.telegram_chat_id), body=msg, ok=ok)
        return ok

    first, second = (via_tg, via_wa) if getattr(ClinicSettings.get(), "primary_messenger", "") == "tg" \
        else (via_wa, via_tg)
    ok = first() or second()
    if ok:
        entry.status = WaitlistEntry.STATUS_OFFERED
        entry.offered_at = timezone.now()
        entry.offered_start = start
        entry.save(update_fields=["status", "offered_at", "offered_start", "updated_at"])
    return ok
