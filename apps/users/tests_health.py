import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings


class HealthTestCase(TestCase):
    def test_healthz_ok_without_login_and_https_redirect(self):
        with override_settings(SECURE_SSL_REDIRECT=True):
            r = self.client.get("/healthz/", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ok"], True)
        self.assertIn("rev", r.json())                       # прямой запрос с сервера
        self.assertEqual(r["Cache-Control"], "no-store")
        r = self.client.get("/healthz/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="8.8.8.8")
        self.assertNotIn("rev", r.json())                    # через nginx — версию не показываем
        self.assertNotIn("rev", self.client.get("/healthz/", REMOTE_ADDR="10.1.1.1").json())

    def test_healthz_reports_db_failure(self):
        with patch("apps.users.health.connection.cursor", side_effect=Exception("db down")):
            r = self.client.get("/healthz/")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["ok"], False)

    def test_backup_dir_and_prefix_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            nightly = Path(d) / "sadaf_backup_2026-01-01_0000.sql.gz"
            nightly.write_bytes(b"x")
            for i in range(3):
                (Path(d) / f"predeploy_2026-01-0{i + 1}_0000.sqlite3.gz").write_bytes(b"x")
            with patch("apps.users.management.commands.backup_database.Command._dump_sqlite",
                       side_effect=lambda src, dest: dest.write_bytes(b"x")), \
                    patch("apps.users.management.commands.backup_database.Command._dump_postgres",
                          side_effect=lambda db, dest: dest.write_bytes(b"x")):
                call_command("backup_database", dir=d, prefix="predeploy_", keep=2, stdout=open("/dev/null", "w"))
            self.assertTrue(nightly.exists())                 # ночные копии не трогаем
            self.assertEqual(len(list(Path(d).glob("predeploy_*"))), 2)
