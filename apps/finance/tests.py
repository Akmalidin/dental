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


class CashShiftOpenActiveBranchTestCase(TestCase):
    """Регрессия: _cashier_branch() игнорировала переключатель филиала в
    сайдбаре и всегда резолвила ГЛАВНЫЙ филиал — на странице кассы
    Филиала #2 показывало "смена не открыта" (там смены правда нет), а
    кнопка "Открыть смену" пыталась открыть смену главного филиала и
    падала с "уже открыта", если там смена уже шла. Теперь
    _cashier_branch читает session["active_branch"], как и сама страница
    кассы (_newui_cashdesk_data)."""

    def setUp(self):
        from apps.finance.models import CashShift

        self.clinic = Clinic.objects.create(name="Клиника CS", slug="clinic-cashshift")
        self.branch1 = Branch.objects.create(name="Филиал 1", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.branch2 = Branch.objects.create(name="Филиал 2", address="-", phone="0", clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="cs_director", name="Директор CS", email="csd@test.local", role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)
        # Смена главного филиала уже открыта — именно она раньше "перехватывала" открытие.
        CashShift.objects.create(branch=self.branch1, opened_by=self.director, opening_cash=0, clinic=self.clinic)
        self.CashShift = CashShift

    def _set_branch(self, branch):
        session = self.client.session
        session["active_branch"] = branch.pk
        session.save()

    def test_open_shift_for_active_non_main_branch_succeeds(self):
        self._set_branch(self.branch2)
        resp = self.client.post("/finance/cashshift/open/", {"opening_cash": "1000"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertTrue(self.CashShift.objects.filter(branch=self.branch2, status=self.CashShift.STATUS_OPEN).exists())

    def test_open_shift_for_main_branch_still_reports_already_open(self):
        self._set_branch(self.branch1)
        resp = self.client.post("/finance/cashshift/open/", {"opening_cash": "1000"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())


class SendToCashierBranchRoutingTestCase(TestCase):
    """«Отправить в кассу» (apps.finance.views.send_to_cashier) раньше слало
    заявку ВСЕМ администраторам клиники сразу, независимо от филиала —
    пациент физически сейчас там, где врач, а не там, где когда-то
    зарегистрирован (Patient.branch — справочное поле, см. изменения
    2026-09-21/22 про общих для клиники пациентов), поэтому заявка должна
    идти кассирам ТЕКУЩЕГО филиала врача (session["active_branch"]), а не
    филиала пациента. Откат на всю клинику — если в филиале врача нет ни
    одного кассира (заявка не должна теряться молча)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника SC", slug="clinic-send-cashier")
        self.branch1 = Branch.objects.create(name="Филиал 1", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.branch2 = Branch.objects.create(name="Филиал 2", address="-", phone="0", clinic=self.clinic)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor = User.objects.create(
            login="sc_doctor", name="Врач SC", email="scdoc@test.local", role=self.doctor_role, clinic=self.clinic,
        )
        self.cashier1 = User.objects.create(
            login="sc_cashier1", name="Кассир Ф1", email="sccash1@test.local", role=self.admin_role, clinic=self.clinic,
        )
        self.cashier1.branches.set([self.branch1])
        self.cashier2 = User.objects.create(
            login="sc_cashier2", name="Кассир Ф2", email="sccash2@test.local", role=self.admin_role, clinic=self.clinic,
        )
        self.cashier2.branches.set([self.branch2])
        self.patient = Patient.objects.create(
            first_name="Пациент", last_name="SC", phone="+996700111222", branch=self.branch1, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.doctor)

    def _set_branch(self, branch):
        session = self.client.session
        session["active_branch"] = branch.pk
        session.save()

    def test_notifies_only_cashiers_of_doctor_active_branch(self):
        """Пациент зарегистрирован в филиале 1, врач сейчас работает в
        филиале 2 — заявка должна дойти до кассира филиала 2, а не 1."""
        from apps.notifications.models import Notification

        self._set_branch(self.branch2)
        resp = self.client.post(f"/finance/payments/send-to-cashier/{self.patient.pk}/", {"amount": "3000"})
        self.assertEqual(resp.status_code, 302)
        notified = set(Notification.objects.filter(type="payment").values_list("user_id", flat=True))
        self.assertEqual(notified, {self.cashier2.pk})

    def test_falls_back_to_whole_clinic_when_no_cashier_in_branch(self):
        """В филиале врача нет ни одного кассира — заявка не теряется,
        уходит всем администраторам клиники (старое поведение как откат)."""
        from apps.notifications.models import Notification

        self.cashier2.branches.clear()
        self._set_branch(self.branch2)
        resp = self.client.post(f"/finance/payments/send-to-cashier/{self.patient.pk}/", {"amount": "3000"})
        self.assertEqual(resp.status_code, 302)
        notified = set(Notification.objects.filter(type="payment").values_list("user_id", flat=True))
        self.assertEqual(notified, {self.cashier1.pk, self.cashier2.pk})


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

    def test_error_body_is_readable_not_generic(self):
        """require_permission() раньше отдавал голый текст "Missing
        permission: ...", который фронтенд (apiErrorMessage/extractFormError)
        не распознавал и подменял на общее "Не удалось сохранить" — теперь
        обычный (не-XHR) POST получает HTML-фрагмент .bg-red-50 с реальной
        причиной, который extractFormError() уже умеет искать."""
        resp = self.client.post("/finance/payments/create/", {
            "patient": self.patient.pk, "amount": "100", "method": "cash", "type": "income",
        })
        self.assertEqual(resp.status_code, 403)
        body = resp.content.decode()
        self.assertIn("bg-red-50", body)
        self.assertIn("Приём оплат", body)  # label права finance.accept_payments

    def test_error_body_is_json_for_xhr(self):
        """Касса шлёт X-Requested-With и ждёт JSON — apiErrorMessage() читает
        data.error."""
        resp = self.client.post(
            "/finance/payments/create/",
            {"patient": self.patient.pk, "amount": "100", "method": "cash", "type": "income"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertIn("Приём оплат", data["error"])
        self.assertEqual(data["error_key"], "missing_permission")


class RequirePermissionExtraRoleTestCase(TestCase):
    """require_permission() должен учитывать не только основную роль
    (user.role), но и дополнительные (user.roles, M2M) — как уже делает
    role_required()/has_role(). Раньше была асимметрия (регрессия из
    commit 212a797): доп. роль с нужным правом require_permission не видел
    вообще, хотя роль-название-based role_required — видел. Именно это
    ломало «дали доступ на финансы + роль директора вторым/доп.» —
    сохранённое на бэкенде добавление доп. роли реально начинает давать
    granular-права только с этим фиксом."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника RP", slug="clinic-req-perm")
        self.branch = Branch.objects.create(name="RP", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.no_perm_role = Role.objects.create(name="no_perm_role_rp", clinic=self.clinic)
        self.admin_main_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.patient = Patient.objects.create(
            first_name="Тест", last_name="Пациент", phone="998", branch=self.branch, clinic=self.clinic
        )
        self.user = User.objects.create(
            login="rp_extra_role_user", name="Доп Ролью", email="rpx@test.local",
            role=self.no_perm_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_no_extra_role_still_blocked(self):
        resp = self.client.post("/finance/payments/create/", {
            "patient": self.patient.pk, "amount": "100", "method": "cash", "type": "income",
        })
        self.assertEqual(resp.status_code, 403)

    def test_extra_role_grants_finance_accept_payments(self):
        self.user.roles.add(self.admin_main_role)
        resp = self.client.post("/finance/payments/create/", {
            "patient": self.patient.pk, "amount": "100", "method": "cash", "type": "income",
        })
        self.assertNotEqual(resp.status_code, 403)


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


class ManualPaymentAllocationTestCase(TestCase):
    """Ручное деление оплаты по приёмам: кассир указывает суммы на приёмы,
    остаток распределяется автоматически; ошибки возвращаются понятным текстом."""

    def setUp(self):
        import json
        from apps.services.models import Service
        from apps.treatments.models import Treatment, TreatmentCure
        self.json = json
        self.clinic = Clinic.objects.create(name="Клиника Р", slug="clinic-alloc")
        self.other = Clinic.objects.create(name="Чужая Р", slug="clinic-alloc-other")
        role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(login="alloc_dir", name="Директор", role=role, clinic=self.clinic)
        self.stranger = User.objects.create(login="alloc_out", name="Чужой", role=role, clinic=self.other)
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Ф", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.patient = Patient.objects.create(first_name="Анна", last_name="Р", phone="+996555111222", clinic=self.clinic)
        svc = Service.objects.create(name="Пломба", price=5000, clinic=self.clinic)
        self.t = []
        for price in (5000, 4000, 3000):
            t = Treatment.objects.create(patient=self.patient, doctor=self.director, branch=self.branch, status="completed")
            TreatmentCure.objects.create(treatment=t, service=svc, doctor=self.director, price=price, quantity=1)
            t.recalculate_total()
            self.t.append(t)
        clear_current_clinic()
        self.c = Client(); self.c.force_login(self.director)

    def tearDown(self):
        clear_current_clinic()

    def _pay(self, amount, alloc=None, client=None):
        data = {"patient": self.patient.pk, "amount": amount, "method": "cash", "type": "income"}
        if alloc is not None:
            data["allocations"] = self.json.dumps([{"treatment": t.pk, "amount": a} for t, a in alloc])
        return (client or self.c).post("/finance/payments/create/", data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def _alloc(self, payment_id):
        from apps.finance.models import PaymentAllocation
        return {a.treatment_id: a.amount for a in PaymentAllocation.objects.filter(payment_id=payment_id)}

    def test_open_treatments_list(self):
        r = self.c.get(f"/finance/patients/{self.patient.pk}/open-treatments/")
        self.assertEqual([row["debt"] for row in r.json()["rows"]], [5000.0, 4000.0, 3000.0])
        other = Client(); other.force_login(self.stranger)
        self.assertEqual(other.get(f"/finance/patients/{self.patient.pk}/open-treatments/").status_code, 404)

    def test_manual_split_and_rest_goes_automatically(self):
        r = self._pay(6000, [(self.t[1], 2500), (self.t[2], 3000)])
        self.assertEqual(r.status_code, 200)
        alloc = self._alloc(r.json()["payment_id"])
        # 2500 + 3000 вручную, оставшиеся 500 — автоматически на самый старый долг
        self.assertEqual(alloc, {self.t[1].pk: 2500, self.t[2].pk: 3000, self.t[0].pk: 500})
        self.t[2].refresh_from_db()
        self.assertEqual(self.t[2].paid_amount, 3000)

    def test_without_split_old_behaviour(self):
        r = self._pay(6000)
        self.assertEqual(self._alloc(r.json()["payment_id"]), {self.t[0].pk: 5000, self.t[1].pk: 1000})

    def test_split_errors(self):
        from apps.finance.models import Payment
        r = self._pay(6000, [(self.t[2], 3500)])
        self.assertEqual(r.status_code, 400)
        self.assertIn("больше его долга", r.json()["error"])
        r = self._pay(3000, [(self.t[1], 2000), (self.t[2], 2000)])
        self.assertEqual(r.status_code, 400)
        self.assertIn("больше, чем сумма оплаты", r.json()["error"])
        self.assertFalse(Payment.all_clinics.exists())


class CashdeskConsistencyTestCase(TestCase):
    """Сверка кассы (жалобы кассиров): долг по приёмам = долгу пациента,
    двойной клик не создаёт второй платёж, смена видна своей клинике,
    недостача при закрытии видна, заявки «В кассу» гаснут после оплаты."""

    def setUp(self):
        from decimal import Decimal
        self.D = Decimal
        self.clinic = Clinic.objects.create(name="Клиника Касса", slug="clinic-cash-cons")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Гл", address="-", phone="0", is_main=True, clinic=self.clinic)
        role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.admin = User.objects.create(login="cash_cons", name="Кассир", role=role, clinic=self.clinic)
        self.admin.branches.add(self.branch)
        self.patient = Patient.objects.create(first_name="Пац", last_name="Касса", phone="+996555000111",
                                              clinic=self.clinic, branch=self.branch)
        self.client = Client()
        self.client.force_login(self.admin)

    def tearDown(self):
        clear_current_clinic()

    def _treatment(self, total):
        from apps.treatments.models import Treatment
        return Treatment.objects.create(patient=self.patient, doctor=self.admin, branch=self.branch,
                                        clinic=self.clinic, status=Treatment.STATUS_COMPLETED, total_amount=total)

    def _pay(self, amount, **extra):
        data = {"patient": self.patient.pk, "amount": amount, "method": "cash", "type": "income",
                "branch": self.branch.pk, "channel": "cashier"}
        data.update(extra)
        return self.client.post("/finance/payments/create/", data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_advance_goes_to_visit_created_later(self):
        r = self._pay(5000)
        self.assertTrue(r.json()["ok"])
        t = self._treatment(self.D(3000))
        t.refresh_from_db()
        self.patient.refresh_from_db()
        self.assertEqual((t.paid_amount, t.debt), (3000, 0))
        self.assertEqual(self.patient.balance, 2000)     # остаток — аванс

    def test_discount_after_payment_does_not_overpay_visit(self):
        t = self._treatment(self.D(10000))
        self._pay(10000, treatment=t.pk)
        t.discount = self.D(2000)
        t.save()
        t.refresh_from_db()
        self.assertEqual(t.paid_amount, 8000)
        t2 = self._treatment(self.D(1500))
        t2.refresh_from_db()
        self.assertEqual(t2.debt, 0)                     # излишек лёг на следующий приём

    def test_double_click_creates_one_payment(self):
        from apps.finance.models import Payment
        self._treatment(self.D(4000))
        a, b = self._pay(4000).json(), self._pay(4000).json()
        self.assertEqual(a["payment_id"], b["payment_id"])
        self.assertTrue(b.get("duplicate"))
        self.assertEqual(Payment.objects.count(), 1)

    def test_shift_gets_branch_clinic_and_close_uses_expected_cash(self):
        from apps.finance.models import CashShift
        clear_current_clinic()
        s = CashShift.all_clinics.create(branch=self.branch, opened_by=self.admin, opening_cash=1000)
        self.assertEqual(s.clinic_id, self.clinic.pk)
        set_current_clinic(self.clinic)
        self._treatment(self.D(500))
        self._pay(500)
        r = self.client.post("/finance/cashshift/%s/close/" % s.pk)
        self.assertEqual(r.json()["expected"], 1500.0)

    def test_auto_close_at_2_and_open_at_8_local_time(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from apps.finance.models import CashShift
        from apps.finance.shift_auto import run
        tz = ZoneInfo("Asia/Tashkent")
        self.clinic.timezone = "Asia/Tashkent"
        self.clinic.save()
        at = lambda d, h, m=0: datetime(2026, 10, d, h, m, tzinfo=tz)
        s = CashShift.objects.create(branch=self.branch, opened_by=self.admin, opening_cash=0, clinic=self.clinic)
        CashShift.objects.filter(pk=s.pk).update(opened_at=at(6, 8, 30))
        self.assertEqual(run(now=at(7, 1, 55)), {"closed": 0, "opened": 0})   # до 02:00 — ещё работает
        self.assertEqual(run(now=at(7, 2, 0)), {"closed": 1, "opened": 0})
        self.assertEqual(run(now=at(7, 7, 55)), {"closed": 0, "opened": 0})   # до 08:00 сама не открывается
        self.assertEqual(run(now=at(7, 8, 0)), {"closed": 0, "opened": 1})
        self.assertEqual(run(now=at(7, 8, 5)), {"closed": 0, "opened": 0})    # вторая не появляется
        # закрыли вручную днём — до утра сама не откроется
        CashShift.objects.filter(status="open").update(status="closed", closed_at=at(7, 15))
        self.assertEqual(run(now=at(7, 18)), {"closed": 0, "opened": 0})
        self.assertEqual(run(now=at(8, 8, 1))["opened"], 1)

    def test_manual_open_at_7_prevents_auto_open(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from apps.finance.models import CashShift
        from apps.finance.shift_auto import run
        tz = ZoneInfo(self.clinic.timezone)
        old = CashShift.objects.create(branch=self.branch, opened_by=self.admin, opening_cash=0, clinic=self.clinic,
                                       status="closed")
        CashShift.objects.filter(pk=old.pk).update(opened_at=datetime(2026, 10, 6, 8, tzinfo=tz))
        early = CashShift.objects.create(branch=self.branch, opened_by=self.admin, opening_cash=0, clinic=self.clinic)
        CashShift.objects.filter(pk=early.pk).update(opened_at=datetime(2026, 10, 7, 7, tzinfo=tz))
        self.assertEqual(run(now=datetime(2026, 10, 7, 8, 5, tzinfo=tz)), {"closed": 0, "opened": 0})

    def test_payment_closes_cashier_requests(self):
        from apps.notifications.models import Notification
        self._treatment(self.D(700))
        other = Patient.objects.create(first_name="Др", last_name="Пац", phone="+996555000999",
                                       clinic=self.clinic, branch=self.branch)
        link = "/finance/payments/?patient=%s" % self.patient.pk
        n = Notification.send(self.admin, "Принять оплату", "x", type="payment", link=link)
        n2 = Notification.send(self.admin, "Принять оплату", "x", type="payment",
                               link="/finance/payments/?patient=%s5" % self.patient.pk)
        self._pay(700)
        self.assertTrue(Notification.objects.get(pk=n.pk).is_read)
        self.assertFalse(Notification.objects.get(pk=n2.pk).is_read)   # другой пациент с похожим id
        self.assertIsNotNone(other)
