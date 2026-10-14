from django.test import Client, TestCase

from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.users.models import Branch, Clinic, Role, User


class StaffAccessSummaryTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="A", slug="sa-a", blocked_features=["warehouse"])
        self.other = Clinic.objects.create(name="B", slug="sa-b")
        set_current_clinic(self.clinic)
        role = lambda n: Role.objects.get(name=n, clinic__isnull=True)  # noqa: E731
        self.director = User.objects.create(login="sa_dir", name="Директор", role=role("admin_main"), clinic=self.clinic)
        self.doc = User.objects.create(login="sa_doc", name="Врач", role=role("doctor"), clinic=self.clinic,
                                       allowed_sections=["appointments", "patients", "treatments"])
        self.br = Branch.objects.create(name="Филиал 2", address="-", phone="0", clinic=self.clinic)
        self.doc.branches.add(self.br)
        self.tech = User.objects.create(login="sa_tech", name="Техник", role=role("technician"), clinic=self.clinic)
        self.stranger = User.objects.create(login="sa_out", name="Чужой", role=role("doctor"), clinic=self.other)
        self.c = Client()
        self.c.force_login(self.director)

    def tearDown(self):
        clear_current_clinic()

    def _get(self, u):
        return self.c.get(f"/new/staff/{u.pk}/access/")

    def test_doctor_summary(self):
        d = self._get(self.doc).json()
        sec = {s["label"]: s for s in d["sections"]}
        self.assertTrue(sec["Пациенты"]["ok"])
        self.assertFalse(sec["Финансы"]["ok"])
        self.assertIn("не отмечено", sec["Финансы"]["why"])
        self.assertFalse(d["fullAccess"])
        self.assertEqual(d["branches"], ["Филиал 2"])
        act = {a["label"]: a for a in d["actions"]}
        self.assertTrue(act["Приём оплат"]["ok"])
        self.assertIn("Доктор", act["Приём оплат"]["why"])
        self.assertFalse(act["Удаление пациентов"]["ok"])
        self.assertFalse([s for s in d["special"] if s["label"].startswith("Зарплаты")][0]["ok"])

    def test_director_blocked_by_tariff_and_tech(self):
        d = self._get(self.director).json()
        sec = {s["label"]: s for s in d["sections"]}
        self.assertFalse(sec["Склад"]["ok"])
        self.assertIn("тарифом", sec["Склад"]["why"])
        self.assertTrue(all(a["ok"] for a in d["actions"]))
        t = self._get(self.tech).json()
        self.assertTrue(t["techOnly"])
        self.assertEqual([s["label"] for s in t["sections"] if s["ok"]], ["Мои заказы (кабинет техника) и Касса"])

    def test_access_rules(self):
        self.assertEqual(self._get(self.stranger).status_code, 404)        # чужая клиника
        c = Client()
        c.force_login(self.doc)
        self.assertNotEqual(c.get(f"/new/staff/{self.director.pk}/access/").status_code, 200)
