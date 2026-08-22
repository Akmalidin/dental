from django.test import TestCase, override_settings
from apps.users.models import Clinic, Branch, ClinicSite


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

    def test_clinic_without_enabled_site_shows_coming_soon(self):
        c = Clinic.objects.create(name="Клиника Без Сайта", slug="dir-no-site")
        Branch.objects.create(name="Центр", address="ул. А", phone="0", is_main=True, clinic=c)
        resp = _get(self.client)
        self.assertContains(resp, "Запись скоро будет доступна")

    def test_clinic_with_enabled_site_shows_booking_links_per_branch(self):
        c = Clinic.objects.create(name="Клиника Записи", slug="dir-book")
        b1 = Branch.objects.create(name="Центр", address="ул. А", phone="0", is_main=True, clinic=c)
        b2 = Branch.objects.create(name="Юг", address="ул. Б", phone="0", clinic=c)
        ClinicSite.objects.create(clinic=c, enabled=True, published=True)
        resp = _get(self.client)
        self.assertContains(resp, f"https://dir-book.stom.asia/book/?branch={b1.pk}")
        self.assertContains(resp, f"https://dir-book.stom.asia/book/?branch={b2.pk}")

    def test_disabled_site_still_shows_coming_soon(self):
        c = Clinic.objects.create(name="Клиника Выкл", slug="dir-disabled")
        Branch.objects.create(name="Центр", address="ул. А", phone="0", is_main=True, clinic=c)
        ClinicSite.objects.create(clinic=c, enabled=False, published=True)
        resp = _get(self.client)
        self.assertContains(resp, "Запись скоро будет доступна")

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
