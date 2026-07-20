"""Отправить локальные изменения в облако.

  python manage.py offline_push --login admin --password ***

Записи, изменённые одновременно и локально, и в облаке с момента последней
синхронизации (offline_cloud.json → last_synced_at), не перезаписываются
молча — они попадают в «Конфликты синхронизации» в облаке для ручного
разрешения персоналом.
"""
import json
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone


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

        cfg_path = getattr(settings, "DATA_DIR", settings.BASE_DIR) / "offline_cloud.json"
        cfg = {}
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
        since = cfg.get("last_synced_at", "")
        sync_started_at = timezone.now().isoformat()

        cli = CloudClient(o["url"])
        if not cli.login(o["login"], o["password"]):
            raise CommandError("Не удалось войти в облако")
        self.stdout.write(f"Отправка {total} записей в облако…")
        res = cli.post_json("/sync/push/", {"blocks": blocks, "since": since})
        if not res.get("ok"):
            raise CommandError("Ошибка push: " + str(res.get("error")))

        cfg["last_synced_at"] = sync_started_at
        try:
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        except Exception:
            pass

        self.stdout.write(self.style.SUCCESS(
            f"Синхронизация завершена. Применено: {sum(res.get('applied', {}).values())} записей."
        ))
        conflicts = res.get("conflicts", 0)
        if conflicts:
            self.stdout.write(self.style.WARNING(
                f"⚠ Конфликтов: {conflicts} — разрешить в облаке в разделе «Конфликты синхронизации» (/sync/conflicts/)."
            ))
