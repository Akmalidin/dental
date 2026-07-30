from django.test import TestCase
from apps.users.models import User, Branch, Clinic
from apps.patients.models import Patient
from apps.finance.forms import PaymentForm
from apps.tenancy import set_current_clinic, clear_current_clinic


class PaymentFormClinicIsolationTestCase(TestCase):
    """Regression test: patient field must never leak patients from other clinics
    into the payment form's dropdown (same class of bug as AppointmentForm —
    ModelForm base_fields queryset frozen, unfiltered, at module-import time)."""

    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника A", slug="clinic-a-fin")
        self.clinic_b = Clinic.objects.create(name="Клиника B", slug="clinic-b-fin")
        self.branch_a = Branch.objects.create(name="A", address="-", phone="0", is_main=True, clinic=self.clinic_a)
        self.branch_b = Branch.objects.create(name="B", address="-", phone="0", is_main=True, clinic=self.clinic_b)
        self.patient_a = Patient.objects.create(
            first_name="Пац", last_name="A", phone="1", branch=self.branch_a, clinic=self.clinic_a
        )
        self.patient_b = Patient.objects.create(
            first_name="Пац", last_name="B", phone="2", branch=self.branch_b, clinic=self.clinic_b
        )

    def tearDown(self):
        clear_current_clinic()

    def test_patient_field_scoped_to_current_clinic(self):
        set_current_clinic(self.clinic_a)
        form = PaymentForm()
        patient_ids = set(form.fields["patient"].queryset.values_list("pk", flat=True))
        self.assertIn(self.patient_a.pk, patient_ids)
        self.assertNotIn(self.patient_b.pk, patient_ids)
