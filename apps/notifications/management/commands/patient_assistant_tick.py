"""Раз в минуту (cron, deploy/update.sh): ИИ-ассистент отвечает пациентам в
WhatsApp/Telegram там, где администратор не ответил вовремя
(apps/notifications/patient_assistant.py)."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "ИИ-ассистент для пациентов: ответить в ждущих чатах"

    def handle(self, *args, **options):
        from apps.settings_clinic.models import ClinicSettings
        from apps.tenancy import clear_current_clinic
        from apps.notifications.patient_assistant import tick_clinic
        total = 0
        for cs in ClinicSettings.objects.filter(ai_patient_bot=True).exclude(clinic=None).select_related("clinic"):
            try:
                total += tick_clinic(cs.clinic)
            except Exception as e:  # noqa: BLE001
                self.stderr.write("clinic %s: %s" % (cs.clinic_id, e))
            finally:
                clear_current_clinic()
        if total:
            self.stdout.write("ответов: %s" % total)
