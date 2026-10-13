"""Напоминания по рассрочкам по настройкам клиники («Деньги → Рассрочки» → ⚙).
Запуск каждый час (cron, см. deploy/update.sh); отправка — в выбранный час.

  --now  — отправить сейчас, не дожидаясь выбранного часа"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Напоминания пациентам о платежах по рассрочке"

    def add_arguments(self, parser):
        parser.add_argument("--now", action="store_true")

    def handle(self, *args, **o):
        from apps.finance.installments import run_reminders
        n = run_reminders(log=lambda m: self.stdout.write(m), force_hour=o["now"])
        self.stdout.write(f"отправлено: {n}")
