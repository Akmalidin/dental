"""Авто-напоминания WhatsApp: за день до приёма, за час, должникам (по расписанию).

Запускать через cron каждые ~15 минут:
    */15 * * * * cd /var/www/sadaf && DJANGO_SETTINGS_MODULE=config.settings.server venv/bin/python manage.py wa_reminders
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q


class Command(BaseCommand):
    help = "WhatsApp авто-напоминания: за день, за час, должникам"

    def handle(self, *args, **opts):
        from apps.notifications.whatsapp import wa_enabled, wa_send_text, render_message
        from apps.notifications.models import MessageTemplate, WaMessage
        from apps.appointments.models import Appointment
        from apps.patients.models import Patient
        from apps.settings_clinic.models import ClinicSettings
        from apps.users.models import Clinic
        from apps.tenancy import set_current_clinic

        if not wa_enabled():
            self.stdout.write("WhatsApp выключен — пропуск")
            return

        now = timezone.now()
        local_hour = timezone.localtime(now).hour
        stat = {"hour": 0, "day": 0, "debt": 0}

        for clinic in Clinic.objects.filter(is_active=True):
            set_current_clinic(clinic)
            cs = ClinicSettings.objects.filter(clinic=clinic).first()
            if cs is None:
                continue

            def tpl(kind):
                t = MessageTemplate.objects.filter(kind=kind, is_active=True).first()
                return t.body if t else None

            def send(patient, appt, body):
                if not (patient and patient.phone and body):
                    return False
                msg = render_message(body, patient=patient, appt=appt)
                ok = wa_send_text(patient.phone, msg)
                WaMessage.objects.create(patient=patient, direction="out",
                                         phone=patient.phone, body=msg, ok=ok)
                return True

            # — за час —
            if cs.wa_remind_hour:
                body = tpl("reminder_hour")
                if body:
                    qs = (Appointment.objects.filter(
                            patient__isnull=False, reminded_hour=False,
                            status__in=["scheduled", "confirmed"],
                            start_at__gt=now, start_at__lte=now + timedelta(minutes=75))
                          .select_related("patient", "doctor"))
                    for a in qs:
                        send(a.patient, a, body)
                        Appointment.objects.filter(pk=a.pk).update(reminded_hour=True)
                        stat["hour"] += 1

            # — за день —
            if cs.wa_remind_day:
                body = tpl("reminder")
                if body:
                    qs = (Appointment.objects.filter(
                            patient__isnull=False, reminded_day=False,
                            status__in=["scheduled", "confirmed"],
                            start_at__gt=now + timedelta(hours=23),
                            start_at__lte=now + timedelta(hours=25))
                          .select_related("patient", "doctor"))
                    for a in qs:
                        send(a.patient, a, body)
                        Appointment.objects.filter(pk=a.pk).update(reminded_day=True)
                        stat["day"] += 1

            # — должникам (раз в N дней, около 10:00 локального времени) —
            if cs.wa_remind_debt_days and cs.wa_remind_debt_days > 0 and local_hour == 10:
                body = tpl("debt")
                if body:
                    cutoff = now - timedelta(days=cs.wa_remind_debt_days)
                    debtors = (Patient.objects.filter(balance__lt=0).exclude(phone="")
                               .filter(Q(last_debt_reminder__isnull=True)
                                       | Q(last_debt_reminder__lte=cutoff)))
                    for p in debtors[:300]:
                        send(p, None, body)
                        Patient.all_objects.filter(pk=p.pk).update(last_debt_reminder=now)
                        stat["debt"] += 1

        self.stdout.write(self.style.SUCCESS(
            "Готово: за час %(hour)s, за день %(day)s, должникам %(debt)s" % stat))
