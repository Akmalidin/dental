import json
from decimal import Decimal
from django.test import TestCase, Client
from apps.users.models import User, Branch, Clinic, Role
from apps.patients.models import Patient
from apps.treatments.models import Treatment
from apps.treatments.forms import TreatmentForm
from apps.tenancy import set_current_clinic, clear_current_clinic


class TreatmentNumberTestCase(TestCase):
    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника A", slug="clinic-a")
        self.clinic_b = Clinic.objects.create(name="Клиника B", slug="clinic-b")
        self.branch_a = Branch.objects.create(name="A", address="-", phone="0", is_main=True, clinic=self.clinic_a)
        self.branch_b = Branch.objects.create(name="B", address="-", phone="0", is_main=True, clinic=self.clinic_b)
        self.doctor_a = User.objects.create(login="doc_a", name="Врач A", email="a@test.local", clinic=self.clinic_a)
        self.doctor_b = User.objects.create(login="doc_b", name="Врач B", email="b@test.local", clinic=self.clinic_b)
        self.patient_a = Patient.objects.create(
            first_name="Пац", last_name="A", phone="1", branch=self.branch_a, clinic=self.clinic_a
        )
        self.patient_b = Patient.objects.create(
            first_name="Пац", last_name="B", phone="2", branch=self.branch_b, clinic=self.clinic_b
        )

    def _make_treatment(self, clinic, branch, doctor, patient):
        return Treatment.objects.create(
            patient=patient, doctor=doctor, branch=branch, clinic=clinic,
        )

    def test_numbering_starts_at_one_per_clinic(self):
        t1 = self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        t2 = self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        self.assertEqual(t1.number, 1)
        self.assertEqual(t2.number, 2)

    def test_numbering_independent_across_clinics(self):
        self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        t_b1 = self._make_treatment(self.clinic_b, self.branch_b, self.doctor_b, self.patient_b)
        self.assertEqual(t_b1.number, 1)  # клиника B не видит нумерацию клиники A

    def test_display_number_falls_back_to_pk_when_number_missing(self):
        t = self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        Treatment.all_objects.filter(pk=t.pk).update(number=None)
        t.refresh_from_db()
        self.assertEqual(t.display_number, t.pk)


class TreatmentFormClinicIsolationTestCase(TestCase):
    """Regression test: patient field must never leak patients from other clinics
    into the treatment form's dropdown (same class of bug as AppointmentForm —
    ModelForm base_fields queryset frozen, unfiltered, at module-import time)."""

    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника C", slug="clinic-a-tf")
        self.clinic_b = Clinic.objects.create(name="Клиника D", slug="clinic-b-tf")
        self.branch_a = Branch.objects.create(name="A", address="-", phone="0", is_main=True, clinic=self.clinic_a)
        self.branch_b = Branch.objects.create(name="B", address="-", phone="0", is_main=True, clinic=self.clinic_b)
        self.patient_a = Patient.objects.create(
            first_name="Пац", last_name="A", phone="3", branch=self.branch_a, clinic=self.clinic_a
        )
        self.patient_b = Patient.objects.create(
            first_name="Пац", last_name="B", phone="4", branch=self.branch_b, clinic=self.clinic_b
        )

    def tearDown(self):
        clear_current_clinic()

    def test_patient_field_scoped_to_current_clinic(self):
        set_current_clinic(self.clinic_a)
        form = TreatmentForm()
        patient_ids = set(form.fields["patient"].queryset.values_list("pk", flat=True))
        self.assertIn(self.patient_a.pk, patient_ids)
        self.assertNotIn(self.patient_b.pk, patient_ids)


class _VisitWizardTestBase(TestCase):
    """Общий сетап для мастера приёма — старый и новый интерфейс бьют в один
    и тот же бэкенд (views_visit.py), поэтому оба покрываются от одних данных."""

    def setUp(self):
        from apps.services.models import Service
        from apps.appointments.models import Appointment
        from django.utils import timezone
        import datetime as dt

        self.clinic = Clinic.objects.create(name="Клиника VW", slug="clinic-visit-wizard")
        self.branch = Branch.objects.create(name="Филиал VW", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(
            login="vw_director", name="Директор VW", email="vwd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.doctor = User.objects.create(
            login="vw_doctor", name="Врач VW", email="vwdoc@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.patient = Patient.objects.create(
            first_name="Приём", last_name="Тестов", phone="+996700321321", branch=self.branch, clinic=self.clinic,
        )
        self.service = Service.objects.create(name="Пломбирование", price=2500, duration=30, clinic=self.clinic)
        today = timezone.localdate()
        start = timezone.make_aware(dt.datetime.combine(today, dt.time(11, 0)))
        end = timezone.make_aware(dt.datetime.combine(today, dt.time(11, 30)))
        self.appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch, service=self.service,
            start_at=start, end_at=end, status=Appointment.STATUS_ARRIVED, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)


class VisitWizardOldInterfaceTestCase(_VisitWizardTestBase):
    """Старый интерфейс (/treatments/visit/...) — регрессия после вынесения
    общей _visit_wizard_context()/_resolve_or_create_visit() для нового интерфейса."""

    def test_visit_start_creates_treatment_moves_appointment_to_in_progress(self):
        resp = self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        self.assertRedirects(resp, f"/treatments/visit/{treatment.pk}/")
        self.assertEqual(treatment.status, Treatment.STATUS_IN_PROGRESS)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "in_progress")

    def test_visit_start_does_not_duplicate_treatment_on_repeat(self):
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        self.assertEqual(Treatment.objects.filter(appointment=self.appt).count(), 1)

    def test_visit_wizard_page_renders(self):
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.get(f"/treatments/visit/{treatment.pk}/")
        self.assertEqual(resp.status_code, 200)

    def test_visit_save_persists_emr_fields_and_teeth(self):
        from apps.treatments.models_teeth import ToothCondition
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        # реальный пользователь всегда сначала открывает страницу мастера —
        # она сеет справочник ToothStatus (_ensure_tooth_statuses), без этого
        # шага сохранённому состоянию зуба не с чем сопоставить статус.
        self.client.get(f"/treatments/visit/{treatment.pk}/")
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/save/",
            data=json.dumps({"complaints": "Болит зуб 26", "diagnosis": "Кариес", "teeth": {"26": "caries"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        treatment.refresh_from_db()
        self.assertEqual(treatment.emr.complaints, "Болит зуб 26")
        tc = ToothCondition.objects.get(patient=self.patient, tooth_number=26)
        self.assertEqual(tc.status.code, "caries")

    def test_visit_commit_completes_treatment_and_creates_cure(self):
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/commit/",
            data=json.dumps({"plan": [{"service_id": self.service.pk, "tooth": "26", "qty": 1, "price": 2500, "done": True}]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        treatment.refresh_from_db()
        self.assertEqual(treatment.status, Treatment.STATUS_COMPLETED)
        self.assertEqual(treatment.cures.count(), 1)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "completed")

    def test_completed_treatment_redirects_away_from_wizard(self):
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        treatment.status = Treatment.STATUS_COMPLETED
        treatment.save(update_fields=["status"])
        resp = self.client.get(f"/treatments/visit/{treatment.pk}/")
        self.assertRedirects(resp, f"/treatments/{treatment.pk}/")


class NewUIVisitWizardTestCase(_VisitWizardTestBase):
    """Новый интерфейс (/new/visit/start/, /new/visitcard/<pk>/) — тот же
    бэкенд (save/upload/commit), что и старый, просто другой вход/страница."""

    def test_newui_visit_start_creates_treatment_and_redirects_to_new_visitcard(self):
        resp = self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        self.assertRedirects(resp, f"/new/visitcard/{treatment.pk}/")
        self.assertEqual(treatment.status, Treatment.STATUS_IN_PROGRESS)

    def test_newui_visit_start_resumes_same_treatment_as_old_interface_would(self):
        """Начать через новый интерфейс, затем «продолжить» тем же URL — не плодит дубли,
        та же дедупликация, что и у старого /treatments/visit/start/."""
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        self.assertEqual(Treatment.objects.filter(appointment=self.appt).count(), 1)

    def test_newui_visitcard_renders_real_data(self):
        import re
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.get(f"/new/visitcard/{treatment.pk}/")
        self.assertEqual(resp.status_code, 200)
        m = re.search(
            r'<script id="newui-real-data" type="application/json">(.*?)</script>',
            resp.content.decode(), re.DOTALL,
        )
        data = json.loads(m.group(1))
        vw = data["visitWizard"]
        self.assertEqual(vw["patientName"], "Тестов Приём")
        self.assertEqual(vw["treatmentId"], treatment.pk)
        self.assertEqual(vw["status"], "in_progress")

    def test_newui_visit_notes_field_persists_via_shared_save_endpoint(self):
        """Расширение visit_save под поле "Прочее" (Treatment.notes) — только для
        нового интерфейса, но не должно ломать старый (он это поле не шлёт)."""
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/save/",
            data=json.dumps({"notes": "Пациент нервничает"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        treatment.refresh_from_db()
        self.assertEqual(treatment.notes, "Пациент нервничает")

    def test_newui_visit_commit_completes_treatment(self):
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/commit/",
            data=json.dumps({"plan": [{"service_id": self.service.pk, "tooth": "14", "qty": 1, "price": 2500, "done": True}]}),
            content_type="application/json",
        )
        self.assertTrue(resp.json()["ok"])
        treatment.refresh_from_db()
        self.assertEqual(treatment.status, Treatment.STATUS_COMPLETED)

    def test_newui_visit_start_no_patient_redirects_to_schedule(self):
        resp = self.client.get("/new/visit/start/")
        self.assertRedirects(resp, "/new/schedule/")
