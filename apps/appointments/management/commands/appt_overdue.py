"""Уведомления о просроченных (забытых) визитах.

Находит записи, у которых время приёма прошло, а исход не отмечен
(статус «Записан»/«Подтверждён»), и шлёт системное уведомление врачу и
администраторам клиники. Уведомляет один раз (флаг overdue_notified).

Запуск по cron каждые ~15 минут:
    */15 * * * * cd /var/www/sadaf && DJANGO_SETTINGS_MODULE=config.settings.server venv/bin/python manage.py appt_overdue
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Системные уведомления о просроченных визитах без отметки исхода"

    def add_arguments(self, parser):
        parser.add_argument("--grace", type=int, default=10,
                            help="через сколько минут после конца считать просроченным")

    def handle(self, *args, **opts):
        from apps.appointments.models import Appointment
        from apps.notifications.models import Notification
        from apps.users.models import Clinic, User, Role
        from apps.tenancy import set_current_clinic

        now = timezone.now()
        cutoff = now - timedelta(minutes=opts.get("grace") or 10)
        total = 0

        for clinic in Clinic.objects.filter(is_active=True):
            set_current_clinic(clinic)
            qs = (Appointment.objects.filter(
                    end_at__lt=cutoff, overdue_notified=False,
                    status__in=[Appointment.STATUS_SCHEDULED, Appointment.STATUS_CONFIRMED])
                  .select_related("patient", "doctor"))
            if not qs.exists():
                continue
            # администраторы клиники (директор/админ) — получают все уведомления
            admins = list(User.objects.filter(
                is_active=True, clinic=clinic,
            ).filter(role__name__in=[Role.ADMIN_MAIN, Role.ADMIN]).distinct())

            for a in qs:
                st = timezone.localtime(a.start_at)
                pname = a.patient.full_name if a.patient else "Без пациента"
                title = "Просроченный визит — отметьте исход"
                body = "%s · %s · врач %s. Запись прошла, статус не отмечен (Пришёл/Не пришёл/Завершён)." % (
                    pname, st.strftime("%d.%m %H:%M"), (a.doctor.name if a.doctor else "—"))
                recipients = set()
                if a.doctor_id:
                    recipients.add(a.doctor)
                for ad in admins:
                    recipients.add(ad)
                for u in recipients:
                    try:
                        Notification.send(u, title, body, type="appointment", link="/appointments/")
                    except Exception:
                        pass
                Appointment.objects.filter(pk=a.pk).update(overdue_notified=True)
                total += 1

        self.stdout.write(self.style.SUCCESS("Уведомлений о просроченных визитах: %d" % total))
