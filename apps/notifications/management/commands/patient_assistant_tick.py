"""ИИ-ассистент отвечает пациентам в WhatsApp/Telegram там, где администратор
не ответил вовремя (apps/notifications/patient_assistant.py).

Cron запускает команду раз в минуту (deploy/update.sh, под flock). Чтобы
пациент не ждал до следующей минуты, команда сама проверяет чаты каждые
--every секунд в течение --loop секунд."""
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "ИИ-ассистент для пациентов: ответить в ждущих чатах"

    def add_arguments(self, parser):
        parser.add_argument("--loop", type=int, default=55, help="сколько секунд работать (0 — один проход)")
        parser.add_argument("--every", type=int, default=3, help="пауза между проходами, сек")

    def _pass(self):
        from apps.settings_clinic.models import ClinicSettings
        from apps.tenancy import clear_current_clinic
        from apps.notifications.patient_assistant import tick_clinic
        total = 0
        for cs in ClinicSettings.objects.filter(ai_patient_bot=True).exclude(clinic=None).select_related("clinic"):
            try:
                total += tick_clinic(cs.clinic, out=self.stdout.write)
            except Exception as e:  # noqa: BLE001
                self.stderr.write("clinic %s: %s" % (cs.clinic_id, e))
            finally:
                clear_current_clinic()
        return total

    def handle(self, *args, **options):
        from django.db import close_old_connections
        deadline = time.monotonic() + max(0, options["loop"])
        while True:
            self._pass()
            close_old_connections()
            if time.monotonic() + options["every"] >= deadline:
                break
            time.sleep(options["every"])
