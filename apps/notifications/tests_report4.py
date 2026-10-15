import io
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.patients.models import Patient
from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.users.models import Branch, Clinic, Role, User


class Report4TestCase(TestCase):
    """Отчёт 4: напоминания после переноса, push только на push-сервисы,
    импорт/экспорт Excel, журнал правок денег."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="О4", slug="rep4")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Ф", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.dir = User.objects.create(login="r4_dir", name="Дир", clinic=self.clinic,
                                       role=Role.objects.get(name="admin_main", clinic__isnull=True))
        self.p = Patient.objects.create(first_name="Анна", last_name="Ли", phone="+996 700 111 222",
                                        notes="важно", clinic=self.clinic)

    def tearDown(self):
        clear_current_clinic()

    def test_reschedule_resets_reminder_flags(self):
        start = timezone.now() + timedelta(days=1)
        a = Appointment.objects.create(patient=self.p, doctor=self.dir, branch=self.branch, start_at=start,
                                       end_at=start + timedelta(minutes=30))
        Appointment.objects.filter(pk=a.pk).update(reminded_day=True, reminded_hour=True)
        a = Appointment.objects.get(pk=a.pk)
        a.notes = "без переноса"
        a.save()
        a.refresh_from_db()
        self.assertTrue(a.reminded_day)
        a.start_at = start + timedelta(days=7)
        a.end_at = a.start_at + timedelta(minutes=30)
        a.save(update_fields=["start_at", "end_at"])
        a.refresh_from_db()
        self.assertFalse(a.reminded_day or a.reminded_hour)

    def test_push_endpoint_whitelist(self):
        from apps.notifications.push import push_endpoint_ok
        self.assertTrue(push_endpoint_ok("https://fcm.googleapis.com/fcm/send/abc"))
        self.assertTrue(push_endpoint_ok("https://web.push.apple.com/QK"))
        self.assertTrue(push_endpoint_ok("https://wns2-db5p.notify.windows.com/w/?token=x"))
        for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1:8021/x", "https://169.254.169.254/",
                    "https://fcm.googleapis.com.evil.io/x", "file:///etc/passwd"):
            self.assertFalse(push_endpoint_ok(bad), bad)
        c = Client()
        c.force_login(self.dir)
        r = c.post("/notifications/push/subscribe/", data='{"endpoint": "http://127.0.0.1:8021/x", "keys": {}}',
                   content_type="application/json")
        self.assertEqual(r.status_code, 400)
        from apps.notifications.models import PushSubscription
        self.assertFalse(PushSubscription.objects.exists())

    def test_excel_import_matches_phone_norm_and_keeps_fields(self):
        from openpyxl import Workbook
        from apps.patients.excel_io import import_patients_xlsx
        wb = Workbook()
        ws = wb.active
        ws.append(["Фамилия", "Имя", "Отчество", "ДР", "Пол", "Телефон", "Доп", "Адрес", "Заметки"])
        ws.append(["Ли", "Анна", "", "", "", "0700111222", "", "Бишкек", ""])
        ws.append(["Новый", "Пациент", "", "", "", "0555000111", "", "", ""])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        created, updated, errors = import_patients_xlsx(buf)
        self.assertEqual((created, updated), (1, 1))
        self.p.refresh_from_db()
        self.assertEqual((self.p.address, self.p.notes), ("Бишкек", "важно"))

    def test_excel_export_formula_is_text(self):
        from openpyxl import Workbook
        from apps.users.utils import neutralize_formulas
        wb = Workbook()
        wb.active.append(['=HYPERLINK("http://x","a")', "текст"])
        neutralize_formulas(wb)
        self.assertEqual(wb.active["A1"].data_type, "s")

    def test_payment_edit_audited(self):
        from apps.finance.models import Payment
        from apps.users.models import AuditEvent
        pay = Payment.objects.create(patient=self.p, amount=1000, branch=self.branch, received_by=self.dir,
                                     clinic=self.clinic, type="income", method="cash")
        clear_current_clinic()
        c = Client()
        c.force_login(self.dir)
        r = c.post(f"/finance/payments/{pay.pk}/edit/", {"patient": self.p.pk, "amount": "700", "method": "cash",
                                                         "type": "income", "branch": self.branch.pk})
        self.assertEqual(r.status_code, 302)
        ev = AuditEvent.objects.get(action="payment_edit")
        self.assertIn({"field": "amount", "old": "1000.00", "new": "700"}, ev.diff)
