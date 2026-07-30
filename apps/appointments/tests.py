from django.test import TestCase, Client
from apps.users.models import User, Branch, Clinic, Role
from apps.patients.models import Patient
from apps.appointments.forms import AppointmentForm
from apps.tenancy import set_current_clinic, clear_current_clinic


class AppointmentFormClinicIsolationTestCase(TestCase):
    """Regression test: patient field must never leak patients from other clinics
    into the appointment form's dropdown (was previously frozen, unfiltered, at
    module-import time — see apps/appointments/forms.py AppointmentForm.__init__)."""

    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника A", slug="clinic-a-appt")
        self.clinic_b = Clinic.objects.create(name="Клиника B", slug="clinic-b-appt")
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
        form = AppointmentForm()
        patient_ids = set(form.fields["patient"].queryset.values_list("pk", flat=True))
        self.assertIn(self.patient_a.pk, patient_ids)
        self.assertNotIn(self.patient_b.pk, patient_ids)


class AppointmentCreateBranchDefaultTestCase(TestCase):
    """Regression test: opening the "new appointment" page must pre-select the
    branch (was previously blank — default only applied on submit, not on the
    initial GET render — see apps/appointments/views.py appointment_create)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника E", slug="clinic-e-branch")
        self.branch = Branch.objects.create(
            name="Главный", address="-", phone="0", is_main=True, clinic=self.clinic
        )
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(
            login="admin_branch", name="Админ", email="admin_branch@test.local",
            role=admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def tearDown(self):
        clear_current_clinic()

    def test_branch_preselected_on_get(self):
        resp = self.client.get("/appointments/create/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["form"].initial.get("branch"), self.branch)
