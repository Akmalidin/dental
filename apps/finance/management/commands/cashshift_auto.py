"""Каждые 5 минут (cron, deploy/update.sh): кассовая смена закрывается в 02:00
и открывается в 08:00 по местному времени клиники (apps/finance/shift_auto.py)."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Автозакрытие (02:00) и автооткрытие (08:00) кассовых смен"

    def handle(self, *args, **options):
        from django.utils import timezone
        from apps.finance.shift_auto import run
        stamp = timezone.now().strftime("%d.%m %H:%M UTC")
        run(log=lambda m: self.stdout.write("%s %s" % (stamp, m)))
