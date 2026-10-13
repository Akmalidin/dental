"""Напоминания по рассрочкам: за день до платежа и через 2 дня после
просрочки (раз на платёж). Запуск раз в день (cron, см. deploy/update.sh)."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Напоминания пациентам о платежах по рассрочке"

    def handle(self, *args, **o):
        from apps.finance.installments import run_reminders
        n = run_reminders(log=lambda m: self.stdout.write(m))
        self.stdout.write(f"отправлено: {n}")
