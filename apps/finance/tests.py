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


class PaymentDeleteSuperadminOnlyTestCase(TestCase):
    """Удаление платежа — жёстко только суперадмин (apps.users.decorators.
    require_superadmin), не через RBAC-права: раньше это была делегируемая
    require_permission("finance.delete_payment"), которую мог выдать
    себе/другим любой admin_main через редактор ролей."""

    def setUp(self):
        from apps.finance.models import Payment

        self.clinic = Clinic.objects.create(name="Клиника PD", slug="clinic-pay-del")
        self.branch = Branch.objects.create(name="PD", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.patient = Patient.objects.create(
            first_name="Плательщик", last_name="Тест", phone="998", branch=self.branch, clinic=self.clinic
        )
        self.admin_main_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name=Role.SUPERADMIN, clinic__isnull=True)

        self.admin_main = User.objects.create(
            login="pd_admin_main", name="Директор PD", email="pdam@test.local",
            role=self.admin_main_role, clinic=self.clinic,
        )
        self.superadmin = User.objects.create(
            login="pd_superadmin", name="Супер PD", email="pdsa@test.local",
            role=self.superadmin_role, clinic=self.clinic,
        )
        self.payment = Payment.objects.create(
            patient=self.patient, branch=self.branch, amount=1000,
            method=Payment.METHOD_CASH, type=Payment.TYPE_INCOME,
            received_by=self.admin_main, clinic=self.clinic,
        )

    def test_admin_main_cannot_delete_even_though_seeded_with_old_permission(self):
        """admin_main получает все права из каталога по умолчанию (см. seed
        0022) — до этой правки этого было достаточно, чтобы удалить платёж
        напрямую через эндпоинт, в обход скрытой в UI кнопки."""
        from apps.finance.models import Payment

        client = Client()
        client.force_login(self.admin_main)
        resp = client.post(f"/finance/payments/{self.payment.pk}/delete/")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Payment.objects.filter(pk=self.payment.pk).exists())

    def test_superadmin_can_delete(self):
        from apps.finance.models import Payment

        client = Client()
        client.force_login(self.superadmin)
        resp = client.post(f"/finance/payments/{self.payment.pk}/delete/")
        self.assertRedirects(resp, "/finance/payments/")
        self.assertFalse(Payment.objects.filter(pk=self.payment.pk).exists())

    def test_finance_delete_payment_permission_removed_from_catalog(self):
        from apps.users.models import Permission

        self.assertFalse(Permission.objects.filter(code="finance.delete_payment").exists())
