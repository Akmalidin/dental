from django.test import TestCase, override_settings
from apps.users.models import Clinic, Branch, ClinicSite, User, Role
from apps.appointments.models import Appointment
from apps.patients.models import Patient


def _get(client, path="/book/"):
    """Апекс stom.asia — StomAsiaRoutingMiddleware переключает urlconf на
    config.urls_marketing только при HTTP_HOST == CRM_BASE_DOMAIN."""
    with override_settings(CRM_BASE_DOMAIN="stom.asia"):
        return client.get(path, HTTP_HOST="stom.asia")


class MarketingDirectoryTestCase(TestCase):
    """/book/ на апексе stom.asia (config.urls_marketing) — каталог всех
    активных клиник: карта + список «блоками», с graceful-деградацией без
    адреса / без включённого публичного сайта (см. план «Публичный сайт
    клиники на stom.asia»)."""

    def test_directory_lists_active_clinics(self):
        Clinic.objects.create(name="Клиника Каталог", slug="dir-clinic")
        resp = _get(self.client)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Клиника Каталог")

    def test_clinic_without_address_shows_placeholder(self):
        Clinic.objects.create(name="Клиника Без Адреса", slug="dir-no-addr")
        resp = _get(self.client)
        self.assertContains(resp, "Адрес: скоро добавим")

    def test_clinic_with_address_shows_it(self):
        c = Clinic.objects.create(name="Клиника С Адресом", slug="dir-addr")
        Branch.objects.create(name="Центр", address="ул. Тестовая 5", phone="0", is_main=True, clinic=c)
        resp = _get(self.client)
        self.assertContains(resp, "ул. Тестовая 5")

    def test_clinic_without_enabled_site_still_bookable_via_generic_page(self):
        c = Clinic.objects.create(name="Клиника Без Сайта", slug="dir-no-site")
        Branch.objects.create(name="Центр", address="ул. А", phone="0", is_main=True, clinic=c)
        resp = _get(self.client)
        self.assertNotContains(resp, "Запись скоро будет доступна")
        self.assertContains(resp, "/book/dir-no-site/")

    def test_clinic_with_enabled_site_shows_booking_links_per_branch(self):
        c = Clinic.objects.create(name="Клиника Записи", slug="dir-book")
        b1 = Branch.objects.create(name="Центр", address="ул. А", phone="0", is_main=True, clinic=c)
        b2 = Branch.objects.create(name="Юг", address="ул. Б", phone="0", clinic=c)
        ClinicSite.objects.create(clinic=c, enabled=True, published=True)
        resp = _get(self.client)
        self.assertContains(resp, f"https://dir-book.stom.asia/book/?branch={b1.pk}")
        self.assertContains(resp, f"https://dir-book.stom.asia/book/?branch={b2.pk}")

    def test_disabled_site_still_bookable_via_generic_page(self):
        c = Clinic.objects.create(name="Клиника Выкл", slug="dir-disabled")
        Branch.objects.create(name="Центр", address="ул. А", phone="0", is_main=True, clinic=c)
        ClinicSite.objects.create(clinic=c, enabled=False, published=True)
        resp = _get(self.client)
        self.assertNotContains(resp, "Запись скоро будет доступна")
        self.assertContains(resp, "/book/dir-disabled/")

    def test_inactive_clinic_not_listed(self):
        Clinic.objects.create(name="Клиника Неактивная", slug="dir-inactive", is_active=False)
        resp = _get(self.client)
        self.assertNotContains(resp, "Клиника Неактивная")

    def test_inactive_branch_not_listed(self):
        c = Clinic.objects.create(name="Клиника Филиалы", slug="dir-branches")
        Branch.objects.create(name="Активный", address="ул. Живая", phone="0", is_main=True, clinic=c)
        Branch.objects.create(name="Закрытый", address="ул. Мёртвая", phone="0", is_active=False, clinic=c)
        resp = _get(self.client)
        self.assertContains(resp, "ул. Живая")
        self.assertNotContains(resp, "ул. Мёртвая")


class MarketingBookClinicTestCase(TestCase):
    """/book/<slug>/ на апексе stom.asia — общая страница записи БЕЗ
    отдельного сайта клиники (apps.marketing.views.book_clinic и др.), для
    клиник без включённого/опубликованного ClinicSite. Важно: она работает
    ВНЕ поддоменного роутинга (apps.tenancy.set_current_clinic не
    выставляется автоматически на апексе), поэтому отдельно проверяем, что
    данные (врачи, филиал, созданная запись/пациент) не утекают из одной
    клиники в другую."""

    domain = "stom.asia"

    def setUp(self):
        doctor_role, _ = Role.objects.get_or_create(name=Role.DOCTOR)
        self.clinic_a = Clinic.objects.create(name="Клиника А", slug="book-a")
        self.branch_a = Branch.objects.create(
            name="Филиал А", address="ул. А", phone="0", is_main=True, clinic=self.clinic_a)
        self.doctor_a = User.objects.create(
            login="book_doc_a", name="Врач А", email="bda@test.local", role=doctor_role, clinic=self.clinic_a)

        self.clinic_b = Clinic.objects.create(name="Клиника Б", slug="book-b")
        self.branch_b = Branch.objects.create(
            name="Филиал Б", address="ул. Б", phone="0", is_main=True, clinic=self.clinic_b)
        self.doctor_b = User.objects.create(
            login="book_doc_b", name="Врач Б", email="bdb@test.local", role=doctor_role, clinic=self.clinic_b)

    def tearDown(self):
        from apps.tenancy import clear_current_clinic
        clear_current_clinic()

    def _get(self, path):
        with override_settings(CRM_BASE_DOMAIN=self.domain):
            return self.client.get(path, HTTP_HOST=self.domain)

    def _post(self, path, data):
        with override_settings(CRM_BASE_DOMAIN=self.domain):
            return self.client.post(path, data, HTTP_HOST=self.domain)

    def _tomorrow(self):
        from datetime import timedelta
        from django.utils import timezone
        return (timezone.localdate() + timedelta(days=1)).isoformat()

    def test_page_lists_only_own_clinic_doctor(self):
        resp = self._get(f"/book/{self.clinic_a.slug}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Врач А")
        self.assertNotContains(resp, "Врач Б")

    def test_branch_step_shown_only_when_multiple_branches(self):
        resp = self._get(f"/book/{self.clinic_a.slug}/")
        self.assertNotContains(resp, ">Филиал<")
        Branch.objects.create(name="Филиал А2", address="ул. А2", phone="0", clinic=self.clinic_a)
        resp = self._get(f"/book/{self.clinic_a.slug}/")
        self.assertContains(resp, "Филиал А")
        self.assertContains(resp, "Филиал А2")

    def test_slots_endpoint_returns_free_slots_for_own_clinic(self):
        resp = self._get(f"/book/{self.clinic_a.slug}/slots/?doctor={self.doctor_a.pk}&date={self._tomorrow()}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("09:00", resp.json()["slots"])

    def test_unknown_clinic_404(self):
        resp = self._get("/book/does-not-exist/")
        self.assertEqual(resp.status_code, 404)
        resp = self._get("/book/does-not-exist/slots/")
        self.assertEqual(resp.status_code, 404)
        resp = self._post("/book/does-not-exist/submit/", {})
        self.assertEqual(resp.status_code, 404)

    def test_submit_creates_appointment_and_patient_scoped_to_correct_clinic(self):
        resp = self._post(f"/book/{self.clinic_b.slug}/submit/", {
            "name": "Тест Пациентов", "phone": "+996700111222",
            "doctor": self.doctor_b.pk, "date": self._tomorrow(), "slot": "10:00",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        appt = Appointment.all_objects.get(doctor=self.doctor_b)
        self.assertEqual(appt.clinic_id, self.clinic_b.pk)
        self.assertEqual(appt.branch_id, self.branch_b.pk)
        patient = Patient.all_objects.get(pk=appt.patient_id)
        self.assertEqual(patient.clinic_id, self.clinic_b.pk)

    def test_submit_rejects_doctor_from_other_clinic(self):
        resp = self._post(f"/book/{self.clinic_a.slug}/submit/", {
            "name": "Тест Пациентов", "phone": "+996700333444",
            "doctor": self.doctor_b.pk, "date": self._tomorrow(), "slot": "10:00",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Appointment.all_objects.filter(doctor=self.doctor_b).exists())


class MarketingRobotsSitemapTestCase(TestCase):
    """robots.txt / sitemap.xml на апексе stom.asia — индексация публичного
    маркетингового сайта разрешена целиком (в отличие от app.sadaf.kg,
    приватного входа персонала — см. config/urls_dev.py _app_robots)."""

    def test_robots_allows_indexing_and_points_to_sitemap(self):
        resp = _get(self.client, "/robots.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("Allow: /", resp.content.decode())
        self.assertIn("Sitemap: http://stom.asia/sitemap.xml", resp.content.decode())

    def test_sitemap_lists_landing_and_directory(self):
        resp = _get(self.client, "/sitemap.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/xml; charset=utf-8")
        body = resp.content.decode()
        self.assertIn("<loc>http://stom.asia/</loc>", body)
        self.assertIn("<loc>http://stom.asia/book/</loc>", body)
