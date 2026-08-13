"""Дымовой тест: все 21 страница нового интерфейса (после разбиения
templates/newui/index.html на отдельные страницы) отдают 200 залогиненному
пользователю. Проверяет только доступность маршрутов — контент/данные
конкретных разделов покрыты точечными тестами в tests.py."""
from django.test import TestCase, Client
from apps.users.models import User, Role, Clinic, Branch
from apps.patients.models import Patient


class NewUISmokeTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Smoke", slug="clinic-smoke-newui")
        self.branch = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.user = User.objects.create(
            login="smoke_admin", name="Смоук Админ", email="smoke@test.local", role=admin_role, clinic=self.clinic,
        )
        self.patient = Patient.objects.create(
            first_name="Смоук", last_name="Пациент", phone="+996700000001", branch=self.branch, clinic=self.clinic,
        )
        from apps.treatments.models import Treatment
        self.treatment = Treatment.objects.create(
            patient=self.patient, doctor=self.user, branch=self.branch, clinic=self.clinic,
        )
        self.client = Client()

    def test_newui_urls_require_login(self):
        resp = self.client.get("/new/")
        self.assertEqual(resp.status_code, 302)

    def test_all_newui_urls_return_200_for_logged_in_user(self):
        self.client.force_login(self.user)
        urls = [
            "/new/", "/new/funnel/", "/new/marketing/", "/new/patients/",
            f"/new/patients/{self.patient.pk}/", "/new/blacklist/", "/new/visits/",
            "/new/schedule/", "/new/treatplans/", "/new/staff/", "/new/services/",
            "/new/warehouse/", "/new/lab/", "/new/cashdesk/", "/new/finance/",
            "/new/accounting/", "/new/reports/", "/new/messages/", "/new/audit/",
            "/new/settings/", f"/new/visitcard/{self.treatment.pk}/",
        ]
        failures = {}
        for u in urls:
            resp = self.client.get(u)
            if resp.status_code != 200:
                failures[u] = resp.status_code
        self.assertEqual(failures, {})
