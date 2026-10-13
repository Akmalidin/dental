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


class SyncPushSecurityTestCase(TestCase):
    """/sync/push/ не даёт трогать чужие клиники, учётные записи и не доступен
    рядовому персоналу; /sync/export/ — только директору/админу."""

    def setUp(self):
        self.clinic = Clinic.objects.create(slug="sync-sec-a", name="A")
        self.other = Clinic.objects.create(slug="sync-sec-b", name="B")
        self.branch = Branch.objects.create(clinic=self.clinic, name="A1", address="-", phone="0", is_main=True)
        self.obranch = Branch.objects.create(clinic=self.other, name="B1", address="-", phone="0", is_main=True)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN_MAIN)
        doc_role, _ = Role.objects.get_or_create(name=Role.DOCTOR)
        self.admin = User.objects.create(login="sync_sec_admin", name="Адм", clinic=self.clinic, role=admin_role)
        self.doctor = User.objects.create(login="sync_sec_doc", name="Врач", clinic=self.clinic, role=doc_role)
        self.victim_user = User.objects.create(login="sync_sec_victim", name="Чужой", clinic=self.other, role=admin_role)
        self.foreign = Patient.objects.create(first_name="Ч", last_name="Ж", phone="+996700000099",
                                              branch=self.obranch, clinic=self.other)

    def _push(self, user, blocks):
        c = Client()
        c.force_login(user)
        return c.post("/sync/push/", data=json.dumps({"blocks": blocks}), content_type="application/json")

    def _snap(self, obj):
        return json.loads(serializers.serialize("json", [obj]))[0]

    def test_doctor_cannot_push_or_export(self):
        self.assertEqual(self._push(self.doctor, []).status_code, 403)
        c = Client()
        c.force_login(self.doctor)
        self.assertEqual(c.get("/sync/export/").status_code, 403)

    def test_cannot_overwrite_other_clinic_patient(self):
        raw = self._snap(self.foreign)
        raw["fields"]["phone2"] = "HACKED"
        raw["fields"]["updated_at"] = timezone.now().isoformat()
        r = self._push(self.admin, [{"model": "patients.Patient", "objects": [raw]}])
        self.assertEqual(r.status_code, 200)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.phone2, "")

    def test_cannot_move_own_record_into_other_clinic_or_create_there(self):
        raw = self._snap(self.foreign)
        raw["pk"] = 987654
        raw["fields"]["phone"] = "+996700000098"
        self._push(self.admin, [{"model": "patients.Patient", "objects": [raw]}])
        self.assertFalse(Patient.all_objects.filter(pk=987654).exists())

    def test_cannot_push_users_or_roles(self):
        raw = self._snap(self.victim_user)
        raw["fields"]["password"] = "pbkdf2_sha256$1$x$y"
        raw["fields"]["clinic"] = self.clinic.pk
        self._push(self.admin, [{"model": "users.User", "objects": [raw]}])
        self.victim_user.refresh_from_db()
        self.assertNotEqual(self.victim_user.password, "pbkdf2_sha256$1$x$y")
        self.assertEqual(self.victim_user.clinic_id, self.other.pk)

    def test_own_clinic_patient_still_applies(self):
        mine = Patient.objects.create(first_name="М", last_name="О", phone="+996700000097",
                                      branch=self.branch, clinic=self.clinic)
        raw = self._snap(mine)
        raw["fields"]["phone2"] = "OK"
        raw["fields"]["updated_at"] = timezone.now().isoformat()
        r = self._push(self.admin, [{"model": "patients.Patient", "objects": [raw]}])
        self.assertEqual(r.json()["applied"]["patients.Patient"], 1)
        mine.refresh_from_db()
        self.assertEqual(mine.phone2, "OK")
