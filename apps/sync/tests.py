import json
import time
from django.test import TestCase, Client
from django.utils import timezone
from django.core import serializers
from apps.users.models import Clinic, Branch, User, Role
from apps.patients.models import Patient
from apps.sync.core import import_blocks
from apps.sync.models import SyncConflict


class ConflictDetectionTestCase(TestCase):
    """Ядро обнаружения конфликтов (import_blocks с since/collect_conflicts):
    конфликт — только когда запись реально менялась И локально, И в облаке
    после последней синхронизации. Иначе применяем/пропускаем без конфликта."""

    def setUp(self):
        self.clinic = Clinic.objects.create(slug="synctest-core", name="SyncTest Core")
        self.branch = Branch.objects.create(
            clinic=self.clinic, name="Main", address="-", phone="0", is_main=True,
        )

    def _snapshot(self, patient):
        return json.loads(serializers.serialize("json", [patient]))[0]

    def test_genuine_conflict_does_not_overwrite_cloud(self):
        p = Patient.objects.create(
            first_name="К", last_name="Т", phone="+996700000001",
            branch=self.branch, clinic=self.clinic,
        )
        since = timezone.now()
        time.sleep(0.02)
        local = self._snapshot(p)
        local["fields"]["phone2"] = "LOCAL-EDIT"
        local["fields"]["updated_at"] = timezone.now().isoformat()

        time.sleep(0.02)
        p.address = "CLOUD-EDIT"
        p.save(update_fields=["address", "updated_at"])

        res = import_blocks(
            [{"model": "patients.Patient", "objects": [local]}],
            since=since, collect_conflicts=True,
        )
        self.assertEqual(len(res["conflicts"]), 1)
        p.refresh_from_db()
        self.assertEqual(p.address, "CLOUD-EDIT")
        self.assertEqual(p.phone2, "")  # локальная правка НЕ применилась молча

    def test_only_local_changed_applies_cleanly(self):
        p = Patient.objects.create(
            first_name="Л", last_name="Т", phone="+996700000002",
            branch=self.branch, clinic=self.clinic,
        )
        since = timezone.now()
        time.sleep(0.02)
        local = self._snapshot(p)
        local["fields"]["phone2"] = "LOCAL-ONLY"
        local["fields"]["updated_at"] = timezone.now().isoformat()

        res = import_blocks(
            [{"model": "patients.Patient", "objects": [local]}],
            since=since, collect_conflicts=True,
        )
        self.assertEqual(len(res["conflicts"]), 0)
        p.refresh_from_db()
        self.assertEqual(p.phone2, "LOCAL-ONLY")

    def test_only_cloud_changed_is_not_reverted(self):
        p = Patient.objects.create(
            first_name="О", last_name="Т", phone="+996700000003",
            branch=self.branch, clinic=self.clinic,
        )
        local = self._snapshot(p)  # снимок ДО облачной правки
        since = timezone.now()
        time.sleep(0.02)
        p.address = "CLOUD-ONLY"
        p.save(update_fields=["address", "updated_at"])

        res = import_blocks(
            [{"model": "patients.Patient", "objects": [local]}],
            since=since, collect_conflicts=True,
        )
        self.assertEqual(len(res["conflicts"]), 0)
        self.assertEqual(res["applied"]["patients.Patient"], 0)
        p.refresh_from_db()
        self.assertEqual(p.address, "CLOUD-ONLY")


class SyncPushViewTestCase(TestCase):
    """Полный путь через view: push с конфликтом создаёт SyncConflict,
    страница конфликтов его показывает, resolve корректно применяет выбор."""

    def setUp(self):
        self.clinic = Clinic.objects.create(slug="synctest-view", name="SyncTest View")
        self.branch = Branch.objects.create(
            clinic=self.clinic, name="Main", address="-", phone="0", is_main=True,
        )
        role, _ = Role.objects.get_or_create(name=Role.ADMIN_MAIN)
        self.staff = User.objects.create(
            login="synctest_view_admin", name="SyncTest ViewAdmin", email="stv@test.local",
            clinic=self.clinic, role=role,
        )
        self.patient = Patient.objects.create(
            first_name="В", last_name="Т", phone="+996700000004",
            branch=self.branch, clinic=self.clinic,
        )

    def test_push_with_conflict_creates_syncconflict_and_resolve_applies_local(self):
        since = timezone.now()
        time.sleep(0.02)
        local = json.loads(serializers.serialize("json", [self.patient]))[0]
        local["fields"]["phone2"] = "VIEW-LOCAL"
        local["fields"]["updated_at"] = timezone.now().isoformat()

        time.sleep(0.02)
        self.patient.address = "VIEW-CLOUD"
        self.patient.save(update_fields=["address", "updated_at"])

        c = Client()
        c.force_login(self.staff)
        resp = c.post(
            "/sync/push/",
            data=json.dumps({
                "blocks": [{"model": "patients.Patient", "objects": [local]}],
                "since": since.isoformat(),
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["conflicts"], 1)

        conflict = SyncConflict.objects.get(clinic=self.clinic, resolved=False)
        self.assertEqual(conflict.model_label, "patients.Patient")

        resp2 = c.get("/sync/conflicts/")
        self.assertEqual(resp2.status_code, 200)

        resp3 = c.post(f"/sync/conflicts/{conflict.pk}/resolve/", {"action": "local"})
        self.assertEqual(resp3.status_code, 302)
        conflict.refresh_from_db()
        self.assertTrue(conflict.resolved)
        self.assertEqual(conflict.resolution, SyncConflict.RESOLUTION_LOCAL)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone2, "VIEW-LOCAL")
