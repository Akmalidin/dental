from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.utils import timezone

from apps.finance.models import Payment
from apps.finance.views import _allocate_income
from apps.patients.models import Patient
from apps.services.models import Service, ServiceCategory
from apps.settings_clinic.models import ClinicSettings
from apps.technicians.models import Technician, TechnicianTask
from apps.tenancy import set_current_clinic, clear_current_clinic
from apps.treatments.models import Treatment, TreatmentCure
from apps.users.models import User, Branch, Clinic, Role
from apps.users.models_salary import SalaryScheme, SalaryCategoryPercent, SalaryPayout
from apps.users.salary_calc import service_salary, payouts_total


class ServiceSalaryTestCase(TestCase):
    """Зарплата «% от услуги»: проценты по категориям, оплаты по приёмам,
    скидка (оба режима), себестоимость, два врача, предоплата, возврат, выплаты."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника З", slug="salary-svc")
        self.other = Clinic.objects.create(name="Чужая", slug="salary-svc-other")
        director = Role.objects.get(name="admin_main", clinic__isnull=True)
        doctor = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(login="sal_dir", name="Директор", role=director, clinic=self.clinic)
        self.doc = User.objects.create(login="sal_doc", name="Ражапова Гулзат", role=doctor, clinic=self.clinic)
        self.doc2 = User.objects.create(login="sal_doc2", name="Алымканов Айбек", role=doctor, clinic=self.clinic)
        self.stranger = User.objects.create(login="sal_out", name="Чужой врач", role=doctor, clinic=self.other)
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Ф", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.patient = Patient.objects.create(first_name="Анна", last_name="Иванова", phone="+996555000222", clinic=self.clinic)
        self.ther = ServiceCategory.objects.create(name="Терапия", clinic=self.clinic)
        self.orto = ServiceCategory.objects.create(name="Ортопедия", clinic=self.clinic)
        self.filling = Service.objects.create(name="Пломба", price=10000, category=self.ther, clinic=self.clinic)
        self.crown = Service.objects.create(name="Коронка", price=20000, category=self.orto, clinic=self.clinic)
        self.xray = Service.objects.create(name="Снимок", price=1000, clinic=self.clinic)
        for d in (self.doc, self.doc2):
            s = SalaryScheme.objects.create(user=d, scheme_type=SalaryScheme.TYPE_PERCENT_SERVICE, percent=10)
            SalaryCategoryPercent.objects.create(scheme=s, category=self.ther, percent=30)
            SalaryCategoryPercent.objects.create(scheme=s, category=self.orto, percent=25)
        self.today = timezone.localdate()
        self.month_start = self.today.replace(day=1)

    def tearDown(self):
        clear_current_clinic()

    def _treatment(self, items, discount=0, patient=None):
        t = Treatment.objects.create(patient=patient or self.patient, doctor=self.doc, branch=self.branch,
                                     status="completed", discount=discount)
        for service, doctor, price in items:
            TreatmentCure.objects.create(treatment=t, service=service, doctor=doctor, price=price, quantity=1)
        t.recalculate_total()
        return t

    def _pay(self, amount, treatment=None, patient=None, kind="income"):
        p = Payment.objects.create(patient=patient or self.patient, treatment=treatment, amount=amount,
                                   branch=self.branch, received_by=self.director, type=kind)
        if kind == "income":
            _allocate_income(p)
        return p

    def _calc(self, doctor=None, **kw):
        return service_salary(doctor or self.doc, self.month_start, self.today, **kw)

    def test_category_percent_and_discount_modes(self):
        t = self._treatment([(self.filling, self.doc, 10000)], discount=2000)
        self._pay(8000, treatment=t)
        self.assertEqual(self._calc()["total"], Decimal("2400.00"))  # 30% от оплаченных 8000
        self.assertEqual(self._calc(discount_shared=False)["total"], Decimal("3000.00"))  # 30% от 10000
        # переключатель в настройках клиники
        cs = ClinicSettings.get(); cs.salary_discount_shared = False; cs.save()
        self.assertEqual(self._calc()["total"], Decimal("3000.00"))

    def test_lab_cost_deducted_in_proportion(self):
        t = self._treatment([(self.crown, self.doc, 20000)])
        tech = Technician.objects.create(name="Техник")
        TechnicianTask.objects.create(technician=tech, treatment=t, service=self.crown,
                                      cure=t.cures.get(), amount=5000)
        self._pay(10000, treatment=t)
        calc = self._calc()
        row = calc["payments"][0]["treatments"][0]["rows"][0]
        self.assertEqual((row["base"], row["cost"], row["percent"]), (Decimal("10000.00"), Decimal("2500.00"), Decimal("25")))
        self.assertEqual(calc["total"], Decimal("1875.00"))  # (10000 − 2500) × 25%

    def test_two_doctors_and_default_percent(self):
        t = self._treatment([(self.filling, self.doc, 6000), (self.filling, self.doc2, 3000), (self.xray, self.doc, 1000)])
        self._pay(10000, treatment=t)
        self.assertEqual(self._calc()["total"], Decimal("1900.00"))  # 6000×30% + 1000×10%
        self.assertEqual(self._calc(self.doc2)["total"], Decimal("900.00"))
        self.assertTrue(self._calc()["payments"][0]["treatments"][0]["other_doctors"])

    def test_one_payment_split_between_visits(self):
        t1 = self._treatment([(self.filling, self.doc, 5000)])
        t2 = self._treatment([(self.filling, self.doc, 5000)])
        self._pay(10000)  # без приёма — распределяется по долгам
        calc = self._calc()
        self.assertEqual(len(calc["payments"]), 1)
        self.assertEqual({t["treatment_id"] for t in calc["payments"][0]["treatments"]}, {t1.pk, t2.pk})
        self.assertEqual(calc["total"], Decimal("3000.00"))

    def test_prepayment_and_overpayment_not_counted(self):
        newcomer = Patient.objects.create(first_name="Б", last_name="Новый", phone="+996555000333", clinic=self.clinic)
        self._pay(5000, patient=newcomer)  # на баланс, приёмов нет
        t = self._treatment([(self.filling, self.doc, 5000)])
        self._pay(7000, treatment=t)  # переплата 2000
        self.assertEqual(self._calc()["total"], Decimal("1500.00"))

    def test_refund_reduces_salary(self):
        t = self._treatment([(self.filling, self.doc, 10000)])
        self._pay(10000, treatment=t)
        self._pay(4000, treatment=t, kind="refund")
        self.assertEqual(self._calc()["total"], Decimal("1800.00"))

    def test_period_uses_payment_date(self):
        t = self._treatment([(self.filling, self.doc, 10000)])
        p = self._pay(10000, treatment=t)
        Payment.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(days=40))
        self.assertEqual(self._calc()["total"], Decimal("0"))
        old = service_salary(self.doc, self.today - timedelta(days=45), self.today)
        self.assertEqual(old["total"], Decimal("3000.00"))

    def test_payout_belongs_to_its_period(self):
        prev_end = self.month_start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        SalaryPayout.objects.create(doctor=self.doc, amount=700, paid_on=self.today,
                                    period_from=prev_start, period_to=prev_end)
        SalaryPayout.objects.create(doctor=self.doc, amount=50, paid_on=self.today)
        self.assertEqual(payouts_total(self.doc, prev_start, prev_end), Decimal("700"))
        self.assertEqual(payouts_total(self.doc, self.month_start, self.today), Decimal("50"))

    # ── страницы ──
    def _client(self, user=None):
        clear_current_clinic()
        c = Client(); c.force_login(user or self.director)
        return c

    def test_pages_payouts_and_access(self):
        t = self._treatment([(self.filling, self.doc, 10000)])
        self._pay(10000, treatment=t)
        c = self._client()
        r = c.get("/new/salary/")
        self.assertEqual(r.status_code, 200)
        data = r.context["real_data"]["salaryData"]
        row = next(x for x in data["rows"] if x["doctorId"] == self.doc.pk)
        self.assertEqual(row["salary"], 3000.0)
        self.assertEqual(row["categoryPercents"][str(self.ther.pk)], 30.0)

        r = c.post(f"/new/salary/{self.doc.pk}/payout/", {
            "amount": "1000", "paid_on": self.today.isoformat(),
            "period_from": self.month_start.isoformat(), "period_to": self.today.isoformat()})
        self.assertEqual(r.json()["ok"], True)
        r = c.get(f"/new/salary/{self.doc.pk}/?from={self.month_start}&to={self.today}")
        d = r.context["real_data"]["salaryDoctor"]
        self.assertEqual((d["earned"], d["paidOut"], d["remaining"]), (3000.0, 1000.0, 2000.0))
        self.assertEqual(d["unpaidSince"], (self.today + timedelta(days=1)).isoformat())
        self.assertEqual(d["payments"][0]["treatments"][0]["rows"][0]["earned"], 3000.0)

        r = c.get(f"/new/salary/{self.doc.pk}/explain/?from={self.month_start}&to={self.today}")
        self.assertContains(r, "Объяснение — Ражапова Гулзат")
        self.assertContains(r, "Пломба")
        self.assertContains(r, "3 000")

        self.assertEqual(c.post(f"/new/salary/{self.doc.pk}/payout/", {"amount": "0"}).status_code, 400)
        self.assertEqual(c.get(f"/new/salary/{self.stranger.pk}/").status_code, 404)
        self.assertEqual(c.post(f"/new/salary/{self.stranger.pk}/payout/", {"amount": "5"}).status_code, 404)

        # врач не видит чужие зарплаты и не может фиксировать выплаты
        dc = self._client(self.doc)
        self.assertNotEqual(dc.get(f"/new/salary/{self.doc2.pk}/").status_code, 200)
        dc.post(f"/new/salary/{self.doc.pk}/payout/", {"amount": "999"})
        self.assertEqual(SalaryPayout.all_clinics.filter(doctor=self.doc).count(), 1)

        po = SalaryPayout.all_clinics.get(doctor=self.doc)
        self.assertEqual(c.post(f"/new/salary/payout/{po.pk}/delete/").json()["ok"], True)
        self.assertFalse(SalaryPayout.all_clinics.exists())

    def test_scheme_edit_saves_category_percents_and_scoped(self):
        c = self._client()
        r = c.post(f"/users/salary/{self.doc.pk}/scheme/", {
            "scheme_type": "percent_service", "percent": "15", "fixed_amount": "0", "has_cats": "1",
            f"cat_{self.ther.pk}": "35", f"cat_{self.orto.pk}": ""})
        self.assertEqual(r.status_code, 302)
        scheme = SalaryScheme.objects.get(user=self.doc)
        self.assertEqual(scheme.percent, Decimal("15"))
        self.assertEqual({cp.category_id: cp.percent for cp in scheme.category_percents.all()},
                         {self.ther.pk: Decimal("35")})
        self.assertEqual(c.post(f"/users/salary/{self.stranger.pk}/scheme/", {"scheme_type": "fixed"}).status_code, 404)
        self.assertFalse(SalaryScheme.objects.filter(user=self.stranger).exists())

    def test_settings_toggle(self):
        c = self._client()
        r = c.post("/new/salary/settings/", {"discount_shared": "0"})
        self.assertEqual(r.json()["discountShared"], False)
        set_current_clinic(self.clinic)
        self.assertFalse(ClinicSettings.get().salary_discount_shared)
        clear_current_clinic()
        dc = self._client(self.doc)
        dc.post("/new/salary/settings/", {"discount_shared": "1"})
        set_current_clinic(self.clinic)
        self.assertFalse(ClinicSettings.get().salary_discount_shared)
