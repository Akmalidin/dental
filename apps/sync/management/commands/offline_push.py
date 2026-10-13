"""Синхронизация офлайн-копии с облаком (то же, что кнопка «Синхронизация»).

  python manage.py offline_push
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Отправить изменения офлайн-копии в облако и получить свежие данные"

    def add_arguments(self, parser):
        # старые параметры принимаются и игнорируются (теперь вход по токену устройства)
        parser.add_argument("--login", default="")
        parser.add_argument("--password", default="")
        parser.add_argument("--url", default="")

    def handle(self, *args, **o):
        from apps.sync.runner import run_sync, SyncError
        try:
            r = run_sync()
        except SyncError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Отправлено {r['pushed']}, получено {r['pulled']}."))
        if r["conflicts"]:
            self.stdout.write(self.style.WARNING(f"Конфликтов: {r['conflicts']} — см. /sync/conflicts/ в облаке."))
        if r["errors"]:
            self.stdout.write(self.style.WARNING(f"Не отправлено (повторится в следующий раз): {r['errors']}"))
        for o_ in r["overlaps"]:
            self.stdout.write(self.style.WARNING("Пересечение записей: " + o_))
