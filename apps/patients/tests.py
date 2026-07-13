from decimal import Decimal
from django.test import TestCase, Client
from apps.users.models import User, Branch
from apps.patients.models import Patient, normalize_phone, SharedPhoneNumber
from apps.treatments.models import Treatment
from apps.finance.models import Payment
from apps.appointments.models import Appointment


class NormalizePhoneTestCase(TestCase):
    def test_different_formats_normalize_to_same_value(self):
        """+996700111222, 0700 111 222 и 996-700-111-222 — один и тот же номер."""
        self.assertEqual(normalize_phone("+996700111222"), normalize_phone("0700 111 222"))
        self.assertEqual(normalize_phone("+996700111222"), normalize_phone("996-700-111-222"))

    def test_phone_norm_saved_on_patient(self):
        branch = Branch.objects.create(name="Main", address="-", phone="0", is_main=True)
        p = Patient.objects.create(first_name="A", last_name="B", phone="+996700111222", branch=branch)
        self.assertEqual(p.phone_norm, "700111222")


class PatientMergeTestCase(TestCase):
    """Объединение дублей: вся история должна переехать на «оригинал»,
    а дубликат — мягко удалиться."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Main", address="-", phone="0", is_main=True)
        self.doctor = User.objects.create(login="doc_merge", name="Doctor Merge", email="d@test.local")
        self.original = Patient.objects.create(
            first_name="Ориг", last_name="Настоящий", phone="+996555000111", branch=self.branch,
        )
        self.dup = Patient.objects.create(
            first_name="Ориг", last_name="Настоящий", phone="0555 000 111", branch=self.branch,
        )

    def test_dup_and_original_share_phone_norm(self):
        """Предпосылка для поиска дублей: разное форматирование — один phone_norm."""
        self.assertEqual(self.original.phone_norm, self.dup.phone_norm)

    def test_merge_reassigns_treatment_and_payment_and_soft_deletes_dup(self):
        from apps.patients.views import merge_patients
        treatment = Treatment.objects.create(
            patient=self.dup, doctor=self.doctor, branch=self.branch,
            status=Treatment.STATUS_COMPLETED, total_amount=Decimal("500"),
        )
        payment = Payment.objects.create(
            patient=self.dup, amount=Decimal("200"), type=Payment.TYPE_INCOME,
            branch=self.branch, received_by=self.doctor,
        )

        merge_patients(self.dup, self.original, self.doctor)

        treatment.refresh_from_db()
        payment.refresh_from_db()
        self.dup.refresh_from_db()
        self.assertEqual(treatment.patient_id, self.original.pk)
        self.assertEqual(payment.patient_id, self.original.pk)
        self.assertTrue(self.dup.is_deleted)

    def test_merge_search_view_finds_dup_by_phone(self):
        """AJAX-поиск кандидатов на объединение должен найти self.original для self.dup."""
        c = Client()
        c.force_login(self.doctor)
        resp = c.get(f"/patients/{self.dup.pk}/merge/search/")
        self.assertEqual(resp.status_code, 200)
        candidate_ids = [row["id"] for row in resp.json()["candidates"]]
        self.assertIn(self.original.pk, candidate_ids)

    def test_merge_confirm_view_end_to_end(self):
        """Полный путь через view (не только функцию): POST на merge/confirm/ переносит
        приём и удаляет дубликат, как в реальном UI."""
        treatment = Treatment.objects.create(
            patient=self.dup, doctor=self.doctor, branch=self.branch,
            status=Treatment.STATUS_COMPLETED, total_amount=Decimal("300"),
        )
        c = Client()
        c.force_login(self.doctor)
        resp = c.post(f"/patients/{self.dup.pk}/merge/confirm/", {"target": self.original.pk})
        self.assertEqual(resp.status_code, 302)
        treatment.refresh_from_db()
        self.dup.refresh_from_db()
        self.assertEqual(treatment.patient_id, self.original.pk)
        self.assertTrue(self.dup.is_deleted)

    def test_merge_always_keeps_older_patient_regardless_of_which_button_was_clicked(self):
        """Кнопку «Есть в базе» могли нажать на ЛЮБОЙ из двух карточек — но
        результат должен быть один и тот же: старая (self.original, создана
        первой в setUp) остаётся, новая (self.dup) удаляется. Здесь специально
        отправляем запрос с pk=self.original (открыли СТАРУЮ карточку) и
        target=self.dup — раньше это привело бы к удалению original с историей."""
        treatment = Treatment.objects.create(
            patient=self.dup, doctor=self.doctor, branch=self.branch,
            status=Treatment.STATUS_COMPLETED, total_amount=Decimal("400"),
        )
        c = Client()
        c.force_login(self.doctor)
        resp = c.post(f"/patients/{self.original.pk}/merge/confirm/", {"target": self.dup.pk})
        self.assertEqual(resp.status_code, 302)
        treatment.refresh_from_db()
        self.original.refresh_from_db()
        self.dup.refresh_from_db()
        self.assertFalse(self.original.is_deleted, "старая карточка должна остаться")
        self.assertTrue(self.dup.is_deleted, "новая карточка должна быть удалена")
        self.assertEqual(treatment.patient_id, self.original.pk)


class PatientPinFilterTestCase(TestCase):
    """Вкладки «С ИИН / Без ИИН» на списке пациентов."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Main", address="-", phone="0", is_main=True)
        self.staff = User.objects.create(login="staff_pin", name="Staff", email="s@test.local")
        self.with_pin = Patient.objects.create(
            first_name="СИИН", last_name="Пациент", phone="+996700000001",
            branch=self.branch, pin="12345678901234",
        )
        self.without_pin = Patient.objects.create(
            first_name="БезИИН", last_name="Пациент", phone="+996700000002", branch=self.branch,
        )

    def test_pin_yes_filter_shows_only_patients_with_pin(self):
        c = Client()
        c.force_login(self.staff)
        resp = c.get("/patients/?pin=yes")
        names = [p.pk for p in resp.context["patients"]]
        self.assertIn(self.with_pin.pk, names)
        self.assertNotIn(self.without_pin.pk, names)

    def test_pin_no_filter_shows_only_patients_without_pin(self):
        c = Client()
        c.force_login(self.staff)
        resp = c.get("/patients/?pin=no")
        names = [p.pk for p in resp.context["patients"]]
        self.assertIn(self.without_pin.pk, names)
        self.assertNotIn(self.with_pin.pk, names)


class PublicBookingDedupTestCase(TestCase):
    """Заявка с сайта не должна создавать второго пациента, если номер уже есть
    в базе (даже отформатированный иначе)."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Main", address="-", phone="0", is_main=True)
        self.existing = Patient.objects.create(
            first_name="Уже", last_name="Существует", phone="0700555444", branch=self.branch,
        )

    def test_existing_patient_reused_for_differently_formatted_phone(self):
        from apps.patients.models import normalize_phone
        from apps.tenancy import get_current_clinic
        # Симулируем то же условие, что использует public_book_submit.
        found = Patient.all_objects.filter(
            clinic=self.existing.clinic, phone_norm=normalize_phone("+996700555444"),
            is_deleted=False,
        ).first()
        self.assertEqual(found, self.existing)


class SharedPhoneNumberTestCase(TestCase):
    """Кнопка «Это другой пациент»: подтверждённый общий номер должен пропасть
    и из dupe_phones (список), и из dupe_patients_count (бейдж в сайдбаре)."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Main", address="-", phone="0", is_main=True)
        self.staff = User.objects.create(login="staff_shared", name="Staff", email="sh@test.local")
        self.p1 = Patient.objects.create(
            first_name="Родственник1", last_name="Общий", phone="+996700999888", branch=self.branch,
        )
        self.p2 = Patient.objects.create(
            first_name="Родственник2", last_name="Общий", phone="0700 999 888", branch=self.branch,
        )

    def test_dupe_phones_includes_pair_before_confirmation(self):
        c = Client()
        c.force_login(self.staff)
        resp = c.get("/patients/?dupes=1")
        ids = [p.pk for p in resp.context["patients"]]
        self.assertIn(self.p1.pk, ids)
        self.assertIn(self.p2.pk, ids)

    def test_mark_not_duplicate_creates_exception_and_removes_from_dupe_list(self):
        c = Client()
        c.force_login(self.staff)
        resp = c.post(f"/patients/{self.p1.pk}/mark-not-duplicate/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(SharedPhoneNumber.objects.filter(phone_norm=self.p1.phone_norm).exists())

        resp = c.get("/patients/?dupes=1")
        ids = [p.pk for p in resp.context["patients"]]
        self.assertNotIn(self.p1.pk, ids)
        self.assertNotIn(self.p2.pk, ids)

    def test_mark_not_duplicate_is_idempotent(self):
        c = Client()
        c.force_login(self.staff)
        c.post(f"/patients/{self.p1.pk}/mark-not-duplicate/")
        c.post(f"/patients/{self.p2.pk}/mark-not-duplicate/")
        self.assertEqual(SharedPhoneNumber.objects.filter(phone_norm=self.p1.phone_norm).count(), 1)
