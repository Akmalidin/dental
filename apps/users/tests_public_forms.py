from datetime import timedelta

from django.core.cache import caches
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.users.models import Branch, Clinic, Role, User
from apps.users.site_views import create_booking


class BookingValidationTestCase(TestCase):
    """Отчёт безопасности №16: время записи и услуга проверяются."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Запись", slug="book-v")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Ф", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.doc = User.objects.create(login="bv_doc", name="Врач", clinic=self.clinic,
                                       role=Role.objects.get(name="doctor", clinic__isnull=True))
        other = Clinic.objects.create(name="Чужая", slug="book-o")
        from apps.services.models import Service
        self.foreign_svc = Service.all_objects.create(name="Чужая услуга", price=1, clinic=other)
        self.own_svc = Service.all_objects.create(name="Своя", price=1, clinic=self.clinic)

    def tearDown(self):
        clear_current_clinic()

    def _book(self, date_str, slot, **kw):
        return create_booking(self.clinic, name="Иван Петров", phone="+996700123456", doctor_id=self.doc.pk,
                              date_str=date_str, slot=slot, **kw)

    def test_bad_hour_past_and_night(self):
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.assertEqual(self._book(tomorrow, "25:00")[1][1], 400)
        self.assertEqual(self._book(tomorrow, "03:00")[1][1], 400)
        self.assertEqual(self._book("2020-01-01", "10:00")[1][1], 400)
        far = (timezone.localdate() + timedelta(days=400)).isoformat()
        self.assertEqual(self._book(far, "10:00")[1][1], 400)
        self.assertFalse(Appointment.all_objects.filter(clinic=self.clinic).exists())

    def test_foreign_service_ignored(self):
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        appt, err = self._book(tomorrow, "10:00", service_id=str(self.foreign_svc.pk))
        self.assertIsNone(err)
        self.assertIsNone(appt.service_id)
        appt2, err = self._book(tomorrow, "11:00", service_id=str(self.own_svc.pk))
        self.assertEqual(appt2.service_id, self.own_svc.pk)


@override_settings(RATELIMIT_ENABLED=True, CACHES={
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "ratelimit": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "rl-test"}})
class PublicFormRateLimitTestCase(TestCase):
    """Отчёт безопасности №8: лимит заявок с одного адреса/номера."""

    def setUp(self):
        caches["ratelimit"].clear()

    def test_access_request_limited(self):
        c = Client()
        codes = []
        for i in range(7):
            r = c.post("/access-request/", {"clinic_name": "К%d" % i, "contact_name": "И", "phone": "0700%06d" % i})
            codes.append(r.status_code)
        from apps.users.models import ClinicAccessRequest
        self.assertEqual(ClinicAccessRequest.objects.count(), 5)

    def test_booking_limited_by_phone(self):
        from apps.users.ratelimit import allow
        self.assertTrue(all(allow("book-phone", "700123456", 3, 60) for _ in range(3)))
        self.assertFalse(allow("book-phone", "700123456", 3, 60))
        self.assertTrue(allow("book-phone", "700999999", 3, 60))


class SafeRedirectTestCase(TestCase):
    """Отчёт безопасности №15: задачи — только POST, Referer чужого сайта игнорируется."""

    def setUp(self):
        from apps.tasks.models import Task
        self.clinic = Clinic.objects.create(name="Задачи", slug="tasks-r")
        set_current_clinic(self.clinic)
        self.u = User.objects.create(login="tr_admin", name="Админ", clinic=self.clinic,
                                     role=Role.objects.get(name="admin_main", clinic__isnull=True))
        self.task = Task.objects.create(title="Т", created_by=self.u)
        clear_current_clinic()

    def test_task_done_post_only_and_safe_referer(self):
        c = Client()
        c.force_login(self.u)
        self.assertEqual(c.get(f"/tasks/{self.task.pk}/done/").status_code, 405)
        r = c.post(f"/tasks/{self.task.pk}/done/", HTTP_REFERER="https://evil.example/phish")
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("evil.example", r["Location"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "done")


class WaApiUrlTestCase(TestCase):
    """Отчёт безопасности №14: адрес Green-API — только https и их домены."""

    def test_safe_url(self):
        from apps.notifications.whatsapp import safe_wa_api_url
        self.assertEqual(safe_wa_api_url("https://7103.api.greenapi.com/"), "https://7103.api.greenapi.com")
        self.assertEqual(safe_wa_api_url("https://api.green-api.com"), "https://api.green-api.com")
        for bad in ("http://api.greenapi.com", "https://127.0.0.1/#", "http://169.254.169.254/x#",
                    "file:///etc/passwd#", "https://greenapi.com.evil.io", "https://evilgreenapi.com",
                    "https://u:p@api.greenapi.com", "https://api.greenapi.com:8443"):
            self.assertEqual(safe_wa_api_url(bad), "", bad)
