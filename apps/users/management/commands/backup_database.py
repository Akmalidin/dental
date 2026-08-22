"""Ежедневный дамп БД (Postgres в проде, SQLite в разработке) + хранение
последних `--keep` (по умолчанию 14) копий в settings.BACKUPS_DIR. Список и
скачивание — вкладка «Резервные копии» в /new/superadmin/ (см.
apps.users.newui_views.newui_superadmin_backups/newui_superadmin_backup_download).

Запускать через cron каждую ночь в 00:00 по Бишкеку (UTC+6). Если сервер
работает в UTC (обычный случай) — это 18:00 UTC ПРЕДЫДУЩЕГО дня:
    0 18 * * * cd /var/www/sadaf && DJANGO_SETTINGS_MODULE=config.settings.server venv/bin/python manage.py backup_database
Если на сервере системный часовой пояс уже Asia/Bishkek — использовать
"0 0 * * *" вместо этого. Перед установкой строки в crontab проверить
`timedatectl` на сервере (эта строка НЕ хранится в репозитории и не
устанавливается автоматически, как и у apps.notifications.wa_reminders/
apps.appointments.appt_overdue — тот же принцип).

Для Postgres требует установленный на уровне ОС клиент `pg_dump` (пакет
postgresql-client или соответствующей версии) — psycopg2-binary (уже в
requirements_server.txt) это Python-драйвер, а не сам pg_dump."""
import gzip
import os
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

FILENAME_PREFIX = "sadaf_backup_"
DEFAULT_KEEP = 14


class Command(BaseCommand):
    help = "Ежедневный дамп БД (pg_dump/sqlite3 backup) + ротация старых копий"

    def add_arguments(self, parser):
        parser.add_argument("--dry", action="store_true", help="не писать/удалять файлы, только показать план")
        parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="сколько последних копий хранить")

    def handle(self, *args, **opts):
        dry = opts.get("dry")
        keep = opts.get("keep") or DEFAULT_KEEP
        backups_dir = Path(settings.BACKUPS_DIR)
        backups_dir.mkdir(parents=True, exist_ok=True)

        db = settings.DATABASES["default"]
        engine = db["ENGINE"]
        stamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d_%H%M")

        if "postgresql" in engine:
            dest = backups_dir / f"{FILENAME_PREFIX}{stamp}.sql.gz"
            if not dry:
                self._dump_postgres(db, dest)
        elif "sqlite3" in engine:
            dest = backups_dir / f"{FILENAME_PREFIX}{stamp}.sqlite3.gz"
            if not dry:
                self._dump_sqlite(db["NAME"], dest)
        else:
            raise CommandError(f"Неподдерживаемый DATABASES['default']['ENGINE']: {engine}")

        if dry:
            self.stdout.write(f"[dry] создал бы: {dest}")
        else:
            size = dest.stat().st_size
            self.stdout.write(self.style.SUCCESS(f"Бэкап создан: {dest} ({size} байт)"))
            try:
                from apps.users.audit import log_audit_event
                log_audit_event(action="backup_create", category="change", object_repr=dest.name)
            except Exception:
                pass

        # Ротация — не критична для успеха самого бэкапа (сбой удаления одного
        # старого файла не должен превращать успешный бэкап в ошибку команды),
        # тот же защитный приём, что и в apps.notifications.wa_reminders.
        self._rotate(backups_dir, keep, dry)

    def _dump_postgres(self, db, dest):
        cmd = [
            "pg_dump", "--no-owner", "--no-privileges",
            "-h", db.get("HOST") or "localhost",
            "-p", str(db.get("PORT") or "5432"),
            "-U", db["USER"], db["NAME"],
        ]
        env = {**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""}
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
        try:
            with gzip.open(dest, "wb") as gz:
                for chunk in iter(lambda: proc.stdout.read(1024 * 1024), b""):
                    gz.write(chunk)
            ret = proc.wait()
            if ret != 0:
                dest.unlink(missing_ok=True)
                raise CommandError(f"pg_dump завершился с кодом {ret}")
        finally:
            proc.stdout.close()

    def _dump_sqlite(self, src_path, dest):
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            src = sqlite3.connect(str(src_path))
            dst = sqlite3.connect(tmp_path)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            with open(tmp_path, "rb") as f_in, gzip.open(dest, "wb") as f_out:
                f_out.writelines(f_in)
        finally:
            os.unlink(tmp_path)

    def _rotate(self, backups_dir, keep, dry):
        files = sorted(backups_dir.glob(f"{FILENAME_PREFIX}*"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            if dry:
                self.stdout.write(f"[dry] удалил бы устаревшую копию: {old.name}")
                continue
            try:
                old.unlink()
                self.stdout.write(f"Удалена устаревшая копия: {old.name}")
            except OSError:
                pass
