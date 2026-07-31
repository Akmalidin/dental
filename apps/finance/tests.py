from django.test import TestCase, Client
from apps.users.models import User, Branch, Clinic, Role
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


class PaymentPermissionTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="PermBranch2", address="-", phone="0", is_main=True)
        self.role = Role.objects.create(name="no_finance_role_test", is_system=True)
        self.user = User.objects.create(login="no_finance_test", name="U", email="u@test.local", role=self.role)
        self.patient = Patient.objects.create(first_name="X", last_name="Y", phone="998", branch=self.branch)
        self.client = Client()
        self.client.force_login(self.user)

    def test_payment_create_blocked_without_permission(self):
        resp = self.client.post("/finance/payments/create/", {
            "patient": self.patient.pk, "amount": "100", "method": "cash", "type": "income",
        })
        self.assertEqual(resp.status_code, 403)

    def test_expense_create_blocked_without_permission(self):
        resp = self.client.post("/finance/expenses/create/", {"amount": "50", "description": "x"})
        self.assertEqual(resp.status_code, 403)
