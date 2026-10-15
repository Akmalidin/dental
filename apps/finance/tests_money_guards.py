from decimal import Decimal

from django.test import Client, TestCase

from apps.finance.models import Payment
from apps.patients.models import Patient
from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.treatments.models import Treatment
from apps.users.models import Branch, Clinic, Role, User


class MoneyGuardsTestCase(TestCase):
    """Отчёт безопасности №3–5: правка платежа по праву, без отрицательных сумм,
    скидка в пределах суммы приёма."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Деньги", slug="money-g")
        set_current_clinic(self.clinic)
        role = lambda n: Role.objects.get(name=n, clinic__isnull=True)  # noqa: E731
        self.admin = User.objects.create(login="mg_admin", name="Админ", role=role("admin"), clinic=self.clinic)
        self.doc = User.objects.create(login="mg_doc", name="Врач", role=role("doctor"), clinic=self.clinic)
        self.nurse = User.objects.create(login="mg_nurse", name="Медсестра", role=role("nurse"), clinic=self.clinic)
        self.branch = Branch.objects.create(name="Ф", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.p = Patient.objects.create(first_name="А", last_name="Б", phone="+996700000901", clinic=self.clinic)
        self.t = Treatment.objects.create(patient=self.p, doctor=self.doc, branch=self.branch, status="completed")
        from apps.services.models import Service
        from apps.treatments.models import TreatmentCure
        svc = Service.objects.create(name="Пломба", price=5000, clinic=self.clinic)
        TreatmentCure.objects.create(treatment=self.t, service=svc, price=5000, quantity=1, doctor=self.doc)
        self.t.recalculate_total()
        self.t.refresh_from_db()
        assert self.t.total_amount == Decimal("5000")
        self.pay = Payment.objects.create(patient=self.p, amount=1000, branch=self.branch, received_by=self.admin,
                                          clinic=self.clinic, type="income", method="cash")

    def tearDown(self):
        clear_current_clinic()

    def _c(self, u):
        c = Client()
        c.force_login(u)
        return c

    def _edit(self, c, amount):
        return c.post(f"/finance/payments/{self.pay.pk}/edit/", {
            "patient": self.p.pk, "amount": amount, "method": "cash", "type": "income", "branch": self.branch.pk})

    def test_edit_payment_requires_permission(self):
        for u in (self.nurse, self.doc):
            self.assertEqual(self._edit(self._c(u), "1").status_code, 403)
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.amount, Decimal("1000"))
        self.assertEqual(self._edit(self._c(self.admin), "900").status_code, 302)
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.amount, Decimal("900"))

    def test_negative_amount_rejected(self):
        r = self._c(self.doc).post("/finance/payments/create/", {
            "patient": self.p.pk, "amount": "-5000", "method": "cash", "type": "income"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertFalse(Payment.objects.filter(amount__lt=0).exists())
        self.assertNotEqual(r.status_code, 200)
        r = self._c(self.admin).post("/finance/cashshift/open/", {"opening_cash": "-100"})
        self.assertEqual(r.status_code, 400)
        r = self._c(self.admin).post("/finance/cashshift/open/", {"opening_cash": "NaN"})
        self.assertEqual(r.status_code, 400)

    def test_discount_clamped_and_permission(self):
        self._c(self.admin).post(f"/treatments/{self.t.pk}/set-discount/", {"discount": "999999"})
        self.t.refresh_from_db()
        self.assertEqual(self.t.discount, Decimal("5000"))           # не больше суммы приёма
        self._c(self.admin).post(f"/treatments/{self.t.pk}/set-discount/", {"discount": "-10"})
        self.t.refresh_from_db()
        self.assertEqual(self.t.discount, Decimal("0"))
        r = self._c(self.nurse).post(f"/treatments/{self.t.pk}/set-discount/", {"discount": "100"})
        self.assertEqual(r.status_code, 403)
        # скидка через оплату тоже ограничена
        self._c(self.doc).post("/finance/payments/create/", {
            "patient": self.p.pk, "treatment": self.t.pk, "amount": "100", "method": "cash", "type": "income",
            "discount": "100000"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.t.refresh_from_db()
        self.assertEqual(self.t.discount, Decimal("5000"))
