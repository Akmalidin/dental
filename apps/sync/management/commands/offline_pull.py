"""Скачать данные клиники с облака в локальную базу.

Пример:
  python manage.py offline_pull --login admin --password *** --url https://sadaf.denta.tw1.ru
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction


class Command(BaseCommand):
    help = "Скачать данные клиники с облака в локальную оффлайн-базу"

    def add_arguments(self, parser):
        parser.add_argument("--login", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--url", default=getattr(settings, "CLOUD_URL", ""))
        parser.add_argument("--clinic", default="", help="ID клиники (для суперадмина)")

    def handle(self, *args, **o):
        from apps.sync.cloud_client import CloudClient
        from apps.sync.core import import_blocks

        url = o["url"]
        if not url:
            raise CommandError("Не задан адрес облака (--url или CLOUD_URL)")
        self.stdout.write(f"Подключение к {url} …")
        cli = CloudClient(url)
        if not cli.login(o["login"], o["password"]):
            raise CommandError("Не удалось войти (проверьте логин/пароль)")
        self.stdout.write(self.style.SUCCESS("Вход выполнен. Загрузка данных…"))

        path = "/sync/export/"
        if o["clinic"]:
            path += f"?clinic={o['clinic']}"
        data = cli.get_json(path)
        if not data.get("ok"):
            raise CommandError("Ошибка экспорта: " + str(data.get("error")))

        blocks = data["blocks"]
        total = sum(b["count"] for b in blocks)
        self.stdout.write(f"Получено объектов: {total}. Запись в локальную базу…")
        with transaction.atomic():
            counts = import_blocks(blocks)

        # запомнить параметры облака для кнопки «Синхронизация» (локальный файл).
        # last_synced_at — момент, на который локальная копия ТОЧНО совпадает с
        # облаком (это время экспорта на сервере) — точка отсчёта для обнаружения
        # конфликтов при последующих push.
        try:
            import json
            cfg = settings.BASE_DIR / "offline_cloud.json"
            cfg.write_text(json.dumps({
                "url": url, "login": o["login"], "password": o["password"],
                "clinic": data["clinic"]["name"],
                "last_synced_at": data.get("exported_at", ""),
            }), encoding="utf-8")
        except Exception:
            pass
        self.stdout.write(self.style.SUCCESS(
            f"Готово! Клиника «{data['clinic']['name']}». Загружено: {sum(counts.values())} записей."
        ))
        for model, n in counts.items():
            if n:
                self.stdout.write(f"  {model}: {n}")
