"""Отправить локальные изменения в облако (БЕТА: last-write-wins по PK).

  python manage.py offline_push --login admin --password ***
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = "Отправить локальные данные клиники в облако (синхронизация вверх)"

    def add_arguments(self, parser):
        parser.add_argument("--login", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--url", default=getattr(settings, "CLOUD_URL", ""))

    def handle(self, *args, **o):
        from apps.sync.cloud_client import CloudClient
        from apps.sync.core import export_clinic
        from apps.users.models import Clinic

        clinic = Clinic.objects.first()
        if not clinic:
            raise CommandError("В локальной базе нет клиники. Сначала offline_pull.")
        blocks = export_clinic(clinic)
        total = sum(b["count"] for b in blocks)

        cli = CloudClient(o["url"])
        if not cli.login(o["login"], o["password"]):
            raise CommandError("Не удалось войти в облако")
        self.stdout.write(f"Отправка {total} записей в облако…")
        res = cli.post_json("/sync/push/", {"blocks": blocks})
        if not res.get("ok"):
            raise CommandError("Ошибка push: " + str(res.get("error")))
        self.stdout.write(self.style.SUCCESS(
            f"Синхронизация завершена. Применено: {sum(res.get('applied', {}).values())} записей."
        ))
