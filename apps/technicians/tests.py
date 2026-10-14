from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from apps.notifications.models import Notification
from apps.patients.models import Patient
from apps.services.models import Service
from apps.technicians.models import Technician, TechnicianTask
from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.treatments.models import Treatment
from apps.users.models import Branch, Clinic, Role, User


class TechnicianCabinetTestCase(TestCase):
    """Кабинет техника: только свои заказы и касса, остальное закрыто."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Лаб", slug="lab-a")
        self.other = Clinic.objects.create(name="Чужая", slug="lab-b")
        set_current_clinic(self.clinic)
        role = lambda n: Role.objects.get(name=n, clinic__isnull=True)  # noqa: E731
        self.admin = User.objects.create(login="lab_admin", name="Админ", role=role("admin_main"), clinic=self.clinic)
        self.doc = User.objects.create(login="lab_doc", name="Врач", role=role("doctor"), clinic=self.clinic)
        self.tech_user = User.objects.create(login="lab", name="Асан  Техник", role=role("technician"), clinic=self.clinic)
        self.branch = Branch.objects.create(name="Ф", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.patient = Patient.objects.create(first_name="Анна", last_name="Иванова", phone="+996555000333",
                                              clinic=self.clinic)
        self.crown = Service.objects.create(name="Коронка", price=20000, clinic=self.clinic)
        self.tech = Technician.objects.create(name="асан техник")
        self.tech2 = Technician.objects.create(name="Другой")
        t = Treatment.objects.create(patient=self.patient, doctor=self.doc, branch=self.branch, status="completed")
        today = timezone.localdate()
        mk = lambda tech, **kw: TechnicianTask.objects.create(  # noqa: E731
            technician=tech, treatment=t, patient=self.patient, service=self.crown, amount=3000,
            transferred_at=today, expected_ready=today + timedelta(days=3), **kw)
        self.mine = mk(self.tech)
        self.alien = mk(self.tech2)
        self.c = Client()
        self.c.force_login(self.tech_user)

    def tearDown(self):
        clear_current_clinic()

    def test_only_cabinet_and_cashdesk_open(self):
        self.assertTrue(self.tech_user.is_technician_only)
        self.assertFalse(self.admin.is_technician_only)
        for url in ("/", "/new/", "/new/patients/", "/new/finance/", "/new/lab/", "/new/warehouse/",
                    "/new/medicines/", "/technicians/", "/new/settings/", "/new/schedule/", "/new/staff/"):
            r = self.c.get(url)
            self.assertEqual((r.status_code, r.get("Location")), (302, "/new/lab/my/"), url)
        r = self.c.post("/new/waitlist/add/", {})
        self.assertEqual(r.status_code, 403)
        r = self.c.post(f"/technicians/orders/{self.alien.pk}/status/", {"status": "installed"})
        self.assertEqual(r.status_code, 403)
        self.alien.refresh_from_db()
        self.assertEqual(self.alien.status, TechnicianTask.STATUS_TRANSFERRED)
        self.assertEqual(self.c.get("/new/cashdesk/").status_code, 200)
        self.assertTrue(self.tech_user.has_granular_perm("finance.accept_payments"))
        page = self.c.get("/new/lab/my/")
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn("/new/cashdesk/", html)
        self.assertNotIn('data-view="patients"', html)
        self.assertNotIn('data-view="warehouse"', html)

    def test_auto_link_by_name_and_only_own_orders(self):
        r = self.c.get("/new/lab/my/data/")
        self.assertEqual(r.status_code, 200)
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.user_id, self.tech_user.pk)       # имя совпало — привязан сам
        ids = [o["id"] for o in r.json()["orders"]]
        self.assertEqual(ids, [self.mine.pk])
        self.assertNotIn("phone", r.content.decode().lower().replace("telephone", ""))
        self.assertEqual(self.c.post(f"/new/lab/my/{self.alien.pk}/status/", {"status": "in_progress"}).status_code,
                         404)

    def test_status_moves_and_notifications(self):
        self.tech.user = self.tech_user
        self.tech.save()
        url = f"/new/lab/my/{self.mine.pk}/status/"
        self.assertEqual(self.c.post(url, {"status": "installed"}).status_code, 400)   # ставит клиника
        self.assertEqual(self.c.post(url, {"status": "ready"}).status_code, 400)       # сначала «в работу»
        self.assertTrue(self.c.post(url, {"status": "in_progress"}).json()["ok"])
        d = self.c.post(url, {"status": "ready"}).json()
        self.assertEqual(d["order"]["status"], "ready")
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.ready_at, timezone.localdate())
        for u in (self.doc, self.admin):
            self.assertTrue(Notification.objects.filter(user=u, title__startswith="Работа готова").exists())
        # клиника вернула на коррекцию — технику уведомление
        admin = Client()
        admin.force_login(self.admin)
        admin.post(f"/technicians/orders/{self.mine.pk}/status/", {"status": "correction"})
        self.assertTrue(Notification.objects.filter(user=self.tech_user, title__startswith="Коррекция").exists())

    def test_upload_checks(self):
        self.tech.user = self.tech_user
        self.tech.save()
        url = f"/new/lab/my/{self.mine.pk}/upload/"
        bad = self.c.post(url, {"file": SimpleUploadedFile("x.exe", b"MZ")})
        self.assertEqual(bad.status_code, 400)
        ok = self.c.post(url, {"file": SimpleUploadedFile("<a>.jpg", b"\xff\xd8\xff", content_type="image/jpeg")})
        self.assertTrue(ok.json()["ok"], ok.content)
        f = ok.json()["order"]["files"][0]
        self.assertNotIn("<", f["name"])
        self.assertIn("?s=", f["url"])
        self.assertEqual(self.c.post(f"/new/lab/my/{self.alien.pk}/upload/",
                                     {"file": SimpleUploadedFile("a.jpg", b"1")}).status_code, 404)

    def test_link_admin_only_same_clinic(self):
        a = Client()
        a.force_login(self.admin)
        r = a.post("/new/lab/link/", {"technician_id": self.tech2.pk, "user_id": self.tech_user.pk})
        self.assertTrue(r.json()["ok"])
        self.tech2.refresh_from_db()
        self.assertEqual(self.tech2.user_id, self.tech_user.pk)
        self.assertEqual(a.post("/new/lab/link/", {"technician_id": self.tech2.pk,
                                                   "user_id": self.doc.pk}).status_code, 400)   # не техник
        stranger = User.objects.create(login="lab_out", name="Чужой", clinic=self.other,
                                       role=Role.objects.get(name="technician", clinic__isnull=True))
        self.assertEqual(a.post("/new/lab/link/", {"technician_id": self.tech2.pk,
                                                   "user_id": stranger.pk}).status_code, 400)
        d = Client()
        d.force_login(self.doc)
        self.assertEqual(d.post("/new/lab/link/", {"technician_id": self.tech.pk,
                                                   "user_id": self.tech_user.pk}).status_code, 403)
        # техник видит заказы того, к кому привязан
        ids = [o["id"] for o in self.c.get("/new/lab/my/data/").json()["orders"]]
        self.assertEqual(ids, [self.alien.pk])

    def test_not_linked_shows_notice(self):
        self.tech.name = "Совсем другое имя"
        self.tech.save()
        r = self.c.get("/new/lab/my/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["real_data"]["labMy"])
        self.assertEqual(self.c.get("/new/lab/my/data/").status_code, 403)
