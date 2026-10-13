"""Первичная настройка офлайн-копии: регистрация в облаке и загрузка данных.

  python manage.py offline_pull --login admin --password *** --url https://soft.stom.asia
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Подключить офлайн-копию к облаку и скачать данные клиники"

    def add_arguments(self, parser):
        parser.add_argument("--login", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--url", default=getattr(settings, "CLOUD_URL", ""))
        parser.add_argument("--name", default="", help="Название компьютера (для списка устройств в облаке)")

    def handle(self, *args, **o):
        from apps.sync.runner import setup, SyncError
        if not o["url"]:
            raise CommandError("Не задан адрес облака (--url или CLOUD_URL)")
        self.stdout.write(f"Подключение к {o['url']} …")
        try:
            clinic, counts = setup(o["url"], o["login"], o["password"], o["name"] or None)
        except SyncError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Готово! Клиника «{clinic}». Загружено: {sum(counts.values())} записей."))
