from django.test import TestCase, Client
from apps.users.models import User, Role


class ReportsPermissionTestCase(TestCase):
    def setUp(self):
        self.role = Role.objects.create(name="no_reports_role_test", is_system=True)
        self.user = User.objects.create(login="no_reports_test", name="U3", email="u3@test.local", role=self.role)
        self.client = Client()
        self.client.force_login(self.user)

    def test_report_finance_blocked_without_permission(self):
        resp = self.client.get("/reports/finance/")
        self.assertEqual(resp.status_code, 403)

    def test_report_doctors_blocked_without_permission(self):
        resp = self.client.get("/reports/doctors/")
        self.assertEqual(resp.status_code, 403)
