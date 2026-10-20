"""Security-тесты по пунктам аудита (отчёты 1–4, 2026-10-15).

Два вида тестов:

1. РЕГРЕССИЯ — пункты, уже закрытые (в т.ч. в #267). Обычные тесты, должны
   проходить. Если кто-то вернёт уязвимость — тест упадёт.

2. ОТКРЫТО — пункты, ещё НЕ исправленные на момент аудита. Тест проверяет
   БЕЗОПАСНОЕ (желаемое) поведение и помечен @unittest.expectedFailure, чтобы
   весь набор оставался зелёным. Когда баг починят, тест начнёт ПРОХОДИТЬ —
   unittest сообщит «unexpected success», и это сигнал: убрать пометку
   expectedFailure (пункт закрыт). Каждый такой тест в докстроке ссылается на
   пункт отчёта.

Запуск:  manage.py test apps.users.tests_security_audit
"""
import json
import unittest

from django.test import Client, TestCase
from django.utils import timezone

from apps.patients.models import Patient
from apps.users.models import Branch, Clinic, Permission, Role, User


def _client(user):
    c = Client()
    c.force_login(user)
    return c


class _Base(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(slug="aud", name="Аудит")
        self.branch = Branch.objects.create(clinic=self.clinic, name="Главный",
                                            address="-", phone="0", is_main=True)
        self.r_dir = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.r_doc = Role.objects.get(name="doctor", clinic__isnull=True)
        self.r_nurse = Role.objects.get(name="nurse", clinic__isnull=True)
        self.director = self._user("aud_dir", self.r_dir, "Dir12345!")
        self.doctor = self._user("aud_doc", self.r_doc, "Doc12345!")
        self.nurse = self._user("aud_nurse", self.r_nurse, "Nur12345!")
        self.patient = Patient.all_objects.create(
            first_name="Иван", last_name="Петров", phone="+996700112233",
            branch=self.branch, clinic=self.clinic)

    def _user(self, login, role, pw):
        u = User.objects.create(login=login, name=login, clinic=self.clinic, role=role)
        u.set_password(pw)
        u.save()
        return u


# ════════════════════════════════════════════════════════════════════════════
# РЕГРЕССИЯ — уже закрытые пункты (должны проходить)
# ════════════════════════════════════════════════════════════════════════════

class RegressionMoneyTestCase(_Base):
    """Отчёт 1 §4, §5; отчёт 3 §2 — закрыто в #267."""

    def test_negative_payment_amount_rejected(self):
        """Отчёт 1 §4: отрицательная сумма прихода не принимается."""
        c = _client(self.doctor)
        r = c.post("/finance/payments/create/", {
            "patient": self.patient.pk, "amount": "-5000", "method": "cash",
            "type": "income", "branch": self.branch.pk,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 400, r.content[:200])
        from apps.finance.models import Payment
        self.assertFalse(Payment.all_clinics.filter(patient=self.patient).exists())

    def test_negative_expense_amount_rejected(self):
        """Отчёт 1 §4: отрицательная сумма расхода не проходит валидацию формы."""
        from apps.finance.forms import ExpenseForm
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            form = ExpenseForm(data={"amount": "-100", "description": "x",
                                     "branch": self.branch.pk, "date": "2026-01-01"})
            self.assertFalse(form.is_valid())
            self.assertIn("amount", form.errors)
        finally:
            clear_current_clinic()

    def test_discount_clamped_to_treatment_total(self):
        """Отчёт 3 §2: скидка на приём ограничена [0, сумма приёма] —
        лишнее больше не превращается в аванс пациента."""
        from decimal import Decimal
        from apps.finance.views import clamp_discount
        from apps.treatments.models import Treatment
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            t = Treatment.objects.create(patient=self.patient, doctor=self.doctor,
                                         branch=self.branch, status="completed")
            t.total_amount = Decimal("1000")
            self.assertEqual(clamp_discount(t, "99999"), Decimal("1000"))
            self.assertEqual(clamp_discount(t, "-50"), Decimal("0"))
            self.assertEqual(clamp_discount(t, "300"), Decimal("300"))
            self.assertIsNone(clamp_discount(t, "abc"))
        finally:
            clear_current_clinic()

    def test_payment_edit_requires_permission(self):
        """Отчёт 1 §3: правка платежа требует права finance.edit_payment."""
        from apps.finance.models import Payment
        pay = Payment.all_clinics.create(patient=self.patient, amount=1000,
                                         branch=self.branch, received_by=self.director)
        # медсестра: ни accept_payments, ни edit_payment — отказ
        r = _client(self.nurse).post(f"/finance/payments/{pay.pk}/edit/", {
            "patient": self.patient.pk, "amount": "1", "method": "cash",
            "type": "income", "branch": self.branch.pk, "notes": "",
        })
        self.assertEqual(r.status_code, 403)
        pay.refresh_from_db()
        self.assertEqual(pay.amount, 1000)


class RegressionTelegramTestCase(_Base):
    """Отчёт 1 §1 — закрыто в #267: карточка привязывается только своим контактом."""

    def test_foreign_contact_does_not_link_card(self):
        from apps.notifications.models import TgChat
        from apps.notifications import tg_patient
        self.patient.telegram_chat_id = None
        self.patient.save(update_fields=["telegram_chat_id"])
        TgChat.objects.create(clinic=self.clinic, chat_id=555000, lang="ru")
        # чужой контакт: user_id контакта != отправителя
        msg = {"chat": {"id": 555000}, "from": {"id": 999111},
               "contact": {"phone_number": self.patient.phone, "user_id": 424242}}
        tg_patient.handle_message(self.clinic, msg, token="t", cs=None)
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.telegram_chat_id)


# ════════════════════════════════════════════════════════════════════════════
# ОТКРЫТО — ещё не исправлено (expectedFailure: тест проходит = баг закрыт)
# ════════════════════════════════════════════════════════════════════════════

class OpenSyncExportTestCase(_Base):
    """Отчёт 1 §6: /sync/export/ не должен отдавать хеши паролей сотрудников."""

    @unittest.expectedFailure
    def test_export_does_not_leak_password_hashes(self):
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            r = _client(self.director).get("/sync/export/")
        finally:
            clear_current_clinic()
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn('"password"', body)
        self.assertNotIn(self.director.password, body)


class OpenStaffEscalationTestCase(_Base):
    """Отчёт 1 §7: обладатель staff.manage не должен назначать admin_main
    (роль директора) ни себе, ни другим."""

    @unittest.expectedFailure
    def test_staff_manage_cannot_self_assign_admin_main(self):
        perm = Permission.objects.get(code="staff.manage")
        hr = Role.objects.create(name="HR", clinic=self.clinic, is_system=False)
        hr.granular_permissions.add(perm)
        self.doctor.role = hr
        self.doctor.save(update_fields=["role"])
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            _client(self.doctor).post(f"/users/{self.doctor.pk}/edit/", {
                "login": "aud_doc", "name": "Doc", "role": self.r_dir.pk, "is_active": "on",
            })
        finally:
            clear_current_clinic()
        self.doctor.refresh_from_db()
        self.assertFalse(self.doctor.is_admin_main)


class OpenProfilePasswordTestCase(_Base):
    """Отчёт 1 §12: смена пароля в профиле без текущего пароля не должна
    проходить."""

    @unittest.expectedFailure
    def test_profile_password_change_requires_current_password(self):
        _client(self.doctor).post("/profile/", {
            "name": "Doc", "password": "Hacked123!", "password2": "Hacked123!",
        })
        self.doctor.refresh_from_db()
        self.assertFalse(self.doctor.check_password("Hacked123!"))


class OpenPushSsrfTestCase(_Base):
    """Отчёт 4 §1: push_subscribe не должен принимать произвольный endpoint
    (SSRF — сервер потом шлёт туда POST). Только https push-сервисы."""

    @unittest.expectedFailure
    def test_push_subscribe_rejects_internal_endpoint(self):
        r = _client(self.doctor).post("/notifications/push/subscribe/", data=json.dumps({
            "subscription": {"endpoint": "http://169.254.169.254/latest/meta-data/",
                             "keys": {"p256dh": "x", "auth": "y"}},
        }), content_type="application/json")
        from apps.notifications.models import PushSubscription
        self.assertFalse(PushSubscription.objects.filter(endpoint__contains="169.254").exists())
        self.assertEqual(r.status_code, 400)


class OpenGetMutationTestCase(_Base):
    """Отчёт 1 §15: изменяющие действия должны требовать POST (иначе CSRF
    через GET-ссылку)."""

    @unittest.expectedFailure
    def test_task_done_rejects_get(self):
        from apps.tasks.models import Task
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            t = Task.objects.create(title="T", clinic=self.clinic, created_by=self.director)
        finally:
            clear_current_clinic()
        _client(self.doctor).get(f"/tasks/{t.pk}/done/")
        t.refresh_from_db()
        self.assertNotEqual(t.status, Task.STATUS_DONE)


class OpenVisitRewriteTestCase(_Base):
    """Отчёт 3 §1: карту завершённого/оплаченного приёма нельзя переписывать
    автосохранением (visit_save) — состав услуг и суммы должны быть
    защищены так же, как в visit_commit."""

    @unittest.expectedFailure
    def test_visit_save_refuses_completed_treatment(self):
        from apps.treatments.models import Treatment
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            t = Treatment.objects.create(patient=self.patient, doctor=self.doctor,
                                         branch=self.branch, status="completed")
        finally:
            clear_current_clinic()
        r = _client(self.doctor).post(f"/treatments/visit/{t.pk}/save/",
                                      data=json.dumps({"plan": []}),
                                      content_type="application/json")
        self.assertEqual(r.status_code, 403)


class OpenAssistantVisibilityTestCase(_Base):
    """Отчёт 3 §6: ИИ-помощник не должен показывать больше, чем доступно
    самому пользователю."""

    def _ctx(self, user):
        from apps.tenancy import set_current_clinic
        set_current_clinic(self.clinic)
        ctx = type("Ctx", (), {})()
        ctx.user = user
        ctx.request = None
        return ctx

    @unittest.expectedFailure
    def test_doctor_day_respects_can_view_all(self):
        """Врач без can_view_all_appointments не должен видеть записи чужих
        врачей через doctor_day."""
        from apps.appointments.models import Appointment
        from apps.notifications import assistant as A
        other = self._user("aud_doc2", self.r_doc, "Doc22345!")
        now = timezone.now()
        Appointment.all_objects.create(clinic=self.clinic, patient=self.patient, doctor=other,
                                       branch=self.branch, start_at=now,
                                       end_at=now + timezone.timedelta(minutes=30))
        self.doctor.can_view_all_appointments = False
        self.doctor.save(update_fields=["can_view_all_appointments"])
        res = A._tool_doctor_day(self._ctx(self.doctor), date=now.date().isoformat())
        self.assertEqual(len(res.get("appointments", [])), 0)

    @unittest.expectedFailure
    def test_patient_details_respects_section_access(self):
        """Сотрудник без доступа к разделу «Пациенты» не должен получать
        телефон/баланс/аллергии пациента через ассистента."""
        from apps.notifications import assistant as A
        self.doctor.allowed_sections = ["calendar"]
        self.doctor.save(update_fields=["allowed_sections"])
        res = A._tool_patient_details(self._ctx(self.doctor), patient_id=self.patient.pk)
        self.assertIn("error", res)


class OpenBookingValidationTestCase(_Base):
    """Отчёт 1 §16: онлайн-запись должна возвращать понятную ошибку на
    неверное время, а не падать с 500, и не создавать записи в прошлом."""

    @unittest.expectedFailure
    def test_invalid_slot_returns_error_not_exception(self):
        from apps.users.site_views import create_booking
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            appt, err = create_booking(
                self.clinic, name="Икс Игрек", phone="+996700119988",
                doctor_id=self.doctor.pk, date_str="2099-01-01", slot="25:00")
        finally:
            clear_current_clinic()
        self.assertIsNone(appt)
        self.assertIsNotNone(err)

    @unittest.expectedFailure
    def test_booking_in_the_past_rejected(self):
        from apps.users.site_views import create_booking
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            appt, err = create_booking(
                self.clinic, name="Икс Игрек", phone="+996700119989",
                doctor_id=self.doctor.pk, date_str="2020-01-01", slot="10:00")
        finally:
            clear_current_clinic()
        self.assertIsNone(appt)
        self.assertIsNotNone(err)
