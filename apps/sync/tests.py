import json
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from django.core import serializers
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.patients.models import Patient
from apps.sync import core
from apps.sync.models import SyncChange, SyncConflict, SyncDevice
from apps.users.models import Branch, Clinic, Role, User


def snap(obj):
    return json.loads(serializers.serialize("json", [obj]))[0]


class _Base(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(slug="sync-a", name="A")
        self.other = Clinic.objects.create(slug="sync-b", name="B")
        self.branch = Branch.objects.create(clinic=self.clinic, name="A1", address="-", phone="0", is_main=True)
        self.obranch = Branch.objects.create(clinic=self.other, name="B1", address="-", phone="0", is_main=True)
        self.admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN_MAIN, clinic=None)
        self.doc_role, _ = Role.objects.get_or_create(name=Role.DOCTOR, clinic=None)
        self.admin = User.objects.create(login="sync_admin", name="Адм", clinic=self.clinic, role=self.admin_role)
        self.doctor = User.objects.create(login="sync_doc", name="Врач", clinic=self.clinic, role=self.doc_role)
        self.since = timezone.now()

    def patient(self, clinic=None, phone="+996700000001", **kw):
        clinic = clinic or self.clinic
        branch = self.branch if clinic == self.clinic else self.obranch
        return Patient.objects.create(first_name=kw.pop("first_name", "Анна"), last_name="Т", phone=phone,
                                      branch=branch, clinic=clinic, **kw)

    def push(self, changes=(), deletions=(), since=None):
        return core.apply_push(list(changes), list(deletions), self.clinic, since or self.since)


class ApplyPushTestCase(_Base):
    """Облако принимает изменения офлайн-копии."""

    def test_new_offline_patient_keeps_device_id_and_does_not_touch_cloud_ids(self):
        cloud = self.patient()
        raw = snap(cloud)
        new_pk = core.device_range(7)[0]
        raw["pk"] = new_pk
        raw["fields"]["first_name"] = "Офлайн"
        raw["fields"]["phone"] = "+996700000002"
        r = self.push([{"model": "patients.Patient", "objects": [raw]}])
        self.assertEqual(r["applied"], 1)
        self.assertEqual(Patient.all_objects.get(pk=new_pk).first_name, "Офлайн")
        cloud.refresh_from_db()
        self.assertEqual(cloud.first_name, "Анна")

    def test_change_only_offline_applies(self):
        p = self.patient()
        time.sleep(0.01)
        self.since = timezone.now()
        raw = snap(p)
        raw["fields"]["address"] = "OFFLINE"
        r = self.push([{"model": "patients.Patient", "objects": [raw]}])
        self.assertEqual((r["applied"], len(r["conflicts"])), (1, 0))
        p.refresh_from_db()
        self.assertEqual(p.address, "OFFLINE")
        self.assertGreaterEqual(p.updated_at, self.since)  # время облака

    def test_both_changed_is_conflict_cloud_kept(self):
        p = self.patient()
        time.sleep(0.01)
        self.since = timezone.now()
        raw = snap(p)
        raw["fields"]["address"] = "OFFLINE"
        time.sleep(0.01)
        p.address = "CLOUD"
        p.save()
        r = self.push([{"model": "patients.Patient", "objects": [raw]}])
        self.assertEqual(len(r["conflicts"]), 1)
        self.assertIn(["patients.Patient", p.pk], r["done"])
        p.refresh_from_db()
        self.assertEqual(p.address, "CLOUD")

    def test_record_deleted_in_cloud_is_not_resurrected(self):
        p = self.patient()
        raw = snap(p)
        Patient.all_objects.filter(pk=p.pk).delete()
        r = self.push([{"model": "patients.Patient", "objects": [raw]}])
        self.assertEqual(r["skipped_deleted"], 1)
        self.assertFalse(Patient.all_objects.filter(pk=p.pk).exists())

    def test_other_clinic_and_denied_models_rejected(self):
        foreign = self.patient(self.other, phone="+996700000009")
        raw = snap(foreign)
        raw["fields"]["address"] = "HACK"
        u = snap(self.admin)
        u["fields"]["is_superadmin"] = True
        r = self.push([{"model": "patients.Patient", "objects": [raw]},
                       {"model": "users.User", "objects": [u]}],
                      [{"model": "patients.Patient", "pk": foreign.pk}])
        self.assertEqual(r["rejected"], 3)
        foreign.refresh_from_db()
        self.assertEqual(foreign.address, "")
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_superadmin)

    def test_deletion_applies_unless_cloud_changed(self):
        from apps.treatments.models import Treatment, TreatmentCure
        from apps.services.models import Service
        p = self.patient()
        svc = Service.objects.create(name="Пломба", price=1000, clinic=self.clinic)
        t = Treatment.objects.create(patient=p, doctor=self.doctor, branch=self.branch, status="completed",
                                     clinic=self.clinic)
        c1 = TreatmentCure.objects.create(treatment=t, service=svc, doctor=self.doctor, price=1000)
        time.sleep(0.01)
        self.since = timezone.now()
        r = self.push(deletions=[{"model": "treatments.TreatmentCure", "pk": c1.pk}])
        self.assertEqual(r["applied"], 1)
        self.assertFalse(TreatmentCure.objects.filter(pk=c1.pk).exists())
        # пациента изменили в облаке после прошлой синхронизации — удаление = конфликт
        time.sleep(0.01)
        p.address = "CLOUD"
        p.save()
        r = self.push(deletions=[{"model": "patients.Patient", "pk": p.pk}])
        self.assertEqual(len(r["conflicts"]), 1)
        self.assertTrue(Patient.all_objects.filter(pk=p.pk).exists())

    def test_new_offline_tooth_condition_merges_with_cloud_twin(self):
        from apps.treatments.models_teeth import ToothCondition
        p = self.patient()
        cloud = ToothCondition.objects.create(patient=p, tooth_number=15, note="cloud")
        ToothCondition.objects.filter(pk=cloud.pk).update(updated_at=self.since - timedelta(minutes=5))
        raw = snap(cloud)
        raw["pk"] = core.device_range(3)[0]
        raw["fields"]["note"] = "offline"
        r = self.push([{"model": "treatments.ToothCondition", "objects": [raw]}])
        self.assertEqual(r["applied"], 1, r)
        self.assertEqual(list(ToothCondition.objects.filter(patient=p).values_list("note", flat=True)), ["offline"])

    def test_new_offline_treatment_gets_next_number_and_payment_recalcs_balance(self):
        from apps.finance.models import Payment
        from apps.treatments.models import Treatment
        p = self.patient()
        t1 = Treatment.objects.create(patient=p, doctor=self.doctor, branch=self.branch, status="completed",
                                      total_amount=500, clinic=self.clinic)
        draft = snap(t1)
        lo = core.device_range(4)[0]
        draft["pk"] = lo
        draft["fields"]["number"] = t1.number   # офлайн выдал тот же номер
        draft["fields"]["total_amount"] = "1000.00"
        pay = {"model": "finance.payment", "pk": lo, "fields": {
            "clinic": self.clinic.pk, "patient": p.pk, "treatment": lo, "branch": self.branch.pk,
            "amount": "1500.00", "type": Payment.TYPE_INCOME, "received_by": self.admin.pk, "method": Payment.METHOD_CASH,
            "created_at": timezone.now().isoformat()}}
        r = self.push([{"model": "finance.Payment", "objects": [pay]},
                       {"model": "treatments.Treatment", "objects": [draft]}])
        self.assertEqual(r["applied"], 2, r)
        self.assertEqual(Treatment.all_objects.get(pk=lo).number, t1.number + 1)
        p.refresh_from_db()
        self.assertEqual(p.balance, 0)


@override_settings(OFFLINE_MODE=True)
class OfflineJournalTestCase(_Base):
    """Офлайн-копия: свой диапазон id, журнал изменений, приём снимка."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._override = override_settings(DATA_DIR=Path(self.tmp.name))
        self._override.enable()
        core.write_local_cfg({"device_id": 5, "token": "x", "url": "http://cloud"})
        core._pk_next.clear()
        core.connect_offline_signals()

    def tearDown(self):
        from django.db.models.signals import pre_save, post_save, post_delete
        for label, model, _ in core._plan_models():
            pre_save.disconnect(sender=model, dispatch_uid=f"sync-pre-{label}")
            post_save.disconnect(sender=model, dispatch_uid=f"sync-post-{label}")
            post_delete.disconnect(sender=model, dispatch_uid=f"sync-del-{label}")
        self._override.disable()
        self.tmp.cleanup()
        super().tearDown()

    def test_new_record_gets_device_range_id_and_journal(self):
        SyncChange.objects.all().delete()
        p = self.patient(phone="+996700000011")
        lo, hi = core.device_range(5)
        self.assertTrue(lo <= p.pk <= hi)
        p2 = self.patient(phone="+996700000012")
        self.assertEqual(p2.pk, p.pk + 1)
        self.assertIn(("patients.Patient", p.pk), core.pending_keys())
        changes, deletions, upto = core.export_changes()
        labels = {b["model"] for b in changes}
        self.assertIn("patients.Patient", labels)
        p2_pk = p2.pk
        p2.delete()
        _c, deletions, _u = core.export_changes()
        self.assertIn({"model": "patients.Patient", "pk": p2_pk}, deletions)

    def test_remote_apply_is_not_journaled_and_users_not_journaled(self):
        SyncChange.objects.all().delete()
        with core.remote_apply():
            self.patient(phone="+996700000013")
        self.admin.name = "Новое имя"
        self.admin.save()
        self.assertEqual(SyncChange.objects.count(), 0)

    def test_clear_journal_keeps_changes_made_during_sync(self):
        SyncChange.objects.all().delete()
        p = self.patient(phone="+996700000014")
        _c, _d, upto = core.export_changes()
        p.address = "во время синхронизации"
        p.save()                       # новая запись журнала с id > upto
        core.clear_journal([["patients.Patient", p.pk]], upto)
        self.assertIn(("patients.Patient", p.pk), core.pending_keys())

    def test_replace_from_snapshot_deletes_stale_and_keeps_pending(self):
        with core.remote_apply():
            gone = self.patient(phone="+996700000015", first_name="Удалён в облаке")
            stays = self.patient(phone="+996700000016", first_name="Есть в облаке")
        pending = self.patient(phone="+996700000017", first_name="Новый офлайн")
        blocks = core.export_clinic(self.clinic)
        for b in blocks:
            if b["model"] == "patients.Patient":
                b["objects"] = [o for o in b["objects"] if o["pk"] == stays.pk]
                b["objects"][0]["fields"]["address"] = "из облака"
        core.replace_from_snapshot(blocks, self.clinic, keep=core.pending_keys())
        self.assertFalse(Patient.all_objects.filter(pk=gone.pk).exists())
        self.assertTrue(Patient.all_objects.filter(pk=pending.pk).exists())
        stays.refresh_from_db()
        self.assertEqual(stays.address, "из облака")
        self.assertNotIn(("patients.Patient", stays.pk), core.pending_keys())

    def test_backup(self):
        self.assertIsNone(core.backup_local_db()) if "sqlite" not in __import__(
            "django.conf").conf.settings.DATABASES["default"]["ENGINE"] else None


class SyncEndpointsTestCase(_Base):
    """Регистрация устройства, токен, доступ."""

    def _register(self, user):
        c = Client()
        c.force_login(user)
        return c.post("/sync/register/", {"name": "ПК ресепшн"})

    def test_register_export_push_with_token(self):
        r = self._register(self.admin).json()
        self.assertTrue(r["ok"])
        dev = SyncDevice.objects.get(pk=r["device_id"])
        self.assertEqual(dev.clinic, self.clinic)
        self.assertNotEqual(dev.token_hash, r["token"])   # хранится только хэш
        auth = {"HTTP_AUTHORIZATION": f"Device {r['device_id']}:{r['token']}"}
        c = Client()
        p = self.patient()
        time.sleep(0.01)
        exp = c.get("/sync/export/", **auth).json()
        self.assertTrue(exp["ok"])
        raw = snap(p)
        raw["fields"]["address"] = "OFFLINE"
        res = c.post("/sync/push/", data=json.dumps({
            "since": exp["exported_at"], "changes": [{"model": "patients.Patient", "objects": [raw]}],
        }), content_type="application/json", **auth).json()
        self.assertEqual(res["applied"], 1)
        self.assertEqual(res["done"], [["patients.Patient", p.pk]])

    def test_doctor_cannot_register_or_export(self):
        self.assertEqual(self._register(self.doctor).status_code, 403)
        c = Client()
        c.force_login(self.doctor)
        self.assertEqual(c.get("/sync/export/").status_code, 403)

    def test_push_requires_valid_active_token(self):
        r = self._register(self.admin).json()
        c = Client()
        c.force_login(self.admin)   # сессии мало — нужен токен устройства
        body = json.dumps({"since": timezone.now().isoformat(), "changes": []})
        self.assertEqual(c.post("/sync/push/", body, content_type="application/json").status_code, 403)
        bad = {"HTTP_AUTHORIZATION": f"Device {r['device_id']}:wrong"}
        self.assertEqual(Client().post("/sync/push/", body, content_type="application/json", **bad).status_code, 403)
        SyncDevice.objects.filter(pk=r["device_id"]).update(is_active=False)
        ok = {"HTTP_AUTHORIZATION": f"Device {r['device_id']}:{r['token']}"}
        self.assertEqual(Client().post("/sync/push/", body, content_type="application/json", **ok).status_code, 403)

    def test_token_stops_working_when_admin_demoted(self):
        r = self._register(self.admin).json()
        self.admin.role = self.doc_role
        self.admin.save()
        ok = {"HTTP_AUTHORIZATION": f"Device {r['device_id']}:{r['token']}"}
        self.assertEqual(Client().get("/sync/export/", **ok).status_code, 403)

    def test_conflict_resolution_only_own_clinic(self):
        p = self.patient()
        raw = snap(p)
        raw["fields"]["address"] = "OFFLINE"
        mine = SyncConflict.objects.create(clinic=self.clinic, model_label="patients.Patient",
                                           object_pk=str(p.pk), local_data=raw, cloud_data=snap(p))
        theirs = SyncConflict.objects.create(clinic=self.other, model_label="patients.Patient",
                                             object_pk=str(p.pk), local_data=raw, cloud_data=snap(p))
        c = Client()
        c.force_login(self.admin)
        self.assertEqual(c.post(f"/sync/conflicts/{theirs.pk}/resolve/", {"action": "local"}).status_code, 404)
        c.post(f"/sync/conflicts/{mine.pk}/resolve/", {"action": "local"})
        p.refresh_from_db()
        self.assertEqual(p.address, "OFFLINE")
