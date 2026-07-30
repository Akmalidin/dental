from decimal import Decimal
from django.test import TestCase
from apps.users.models import User, Branch, Clinic
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
