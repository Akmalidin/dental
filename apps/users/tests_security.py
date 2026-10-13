"""Аудит безопасности: чужая клиника не может читать/менять данные и
сотрудников, отключённый REST API, очистка внешнего текста от HTML."""
import json

from django.test import Client, TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, Cabinet
from apps.patients.models import Patient
from apps.users.models import Branch, Clinic, Role, User


class CrossClinicSecurityTestCase(TestCase):
    def setUp(self):
        self.a = Clinic.objects.create(slug="sec-a", name="A")
        self.b = Clinic.objects.create(slug="sec-b", name="B")
        self.ba = Branch.objects.create(clinic=self.a, name="A1", address="-", phone="0", is_main=True)
        self.bb = Branch.objects.create(clinic=self.b, name="B1", address="-", phone="0", is_main=True)
        director = Role.objects.get(name="admin_main", clinic__isnull=True)
        doctor = Role.objects.get(name="doctor", clinic__isnull=True)
        self.dir_a = User.objects.create(login="sec_dir_a", name="Директор А", clinic=self.a, role=director)
        self.dir_a.set_password("Original123!")
        self.dir_a.save()
        self.doc_a = User.objects.create(login="sec_doc_a", name="Врач А", clinic=self.a, role=doctor)
        self.dir_b = User.objects.create(login="sec_dir_b", name="Директор Б", clinic=self.b, role=director)
        self.doc_b = User.objects.create(login="sec_doc_b", name="Врач Б", clinic=self.b, role=doctor)
        self.p_a = Patient.all_objects.create(first_name="Анна", last_name="А", phone="+996700000801",
                                              branch=self.ba, clinic=self.a)

    def client_for(self, user):
        c = Client()
        c.force_login(user)
        return c

    # ── REST API ────────────────────────────────────────────────────────────
    def test_rest_api_disabled_except_calendar(self):
        c = self.client_for(self.doc_a)
        for url in ("/api/v1/patients/", f"/api/v1/patients/{self.p_a.pk}/", "/api/v1/auth/users/",
                    f"/api/v1/auth/users/{self.dir_b.pk}/", "/api/v1/treatments/1/", "/api/v1/auth/login/",
                    "/api/docs/", "/api/schema/"):
            self.assertEqual(c.get(url).status_code, 404, url)
        r = c.patch(f"/api/v1/auth/users/{self.doc_a.pk}/", data=json.dumps({"role_id": 1}),
                    content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_calendar_shows_only_own_clinic(self):
        now = timezone.now()
        Appointment.all_objects.create(clinic=self.a, patient=self.p_a, doctor=self.doc_a, branch=self.ba,
                                       start_at=now, end_at=now + timezone.timedelta(minutes=30))
        p_b = Patient.all_objects.create(first_name="Чужой", last_name="Б", phone="+996700000802",
                                         branch=self.bb, clinic=self.b)
        Appointment.all_objects.create(clinic=self.b, patient=p_b, doctor=self.doc_b, branch=self.bb,
                                       start_at=now, end_at=now + timezone.timedelta(minutes=30))
        r = self.client_for(self.dir_b).get("/api/v1/appointments/calendar/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Чужой", body)
        self.assertNotIn("Анна", body)

    def test_jwt_header_not_accepted(self):
        r = Client().get("/api/v1/appointments/calendar/", HTTP_AUTHORIZATION="Bearer abc.def.ghi")
        self.assertIn(r.status_code, (401, 403))

    # ── Сотрудники другой клиники ───────────────────────────────────────────
    def test_director_cannot_change_password_of_other_clinic(self):
        self.client_for(self.dir_b).post(f"/users/{self.dir_a.pk}/set-password/", {"new_password": "Hacked123!"})
        self.dir_a.refresh_from_db()
        self.assertTrue(self.dir_a.check_password("Original123!"))

    def test_director_cannot_delete_or_edit_other_clinic_staff(self):
        c = self.client_for(self.dir_b)
        c.post(f"/users/{self.doc_a.pk}/delete/")
        c.post(f"/users/{self.doc_a.pk}/edit/", {"login": "hacked", "name": "HACK"})
        self.doc_a.refresh_from_db()
        self.assertTrue(self.doc_a.is_active)
        self.assertEqual(self.doc_a.name, "Врач А")
        self.assertEqual(c.get(f"/users/schedule/{self.doc_a.pk}/edit/").status_code, 404)

    def test_director_still_manages_own_staff(self):
        self.client_for(self.dir_a).post(f"/users/{self.doc_a.pk}/set-password/", {"new_password": "NewPass123!"})
        self.doc_a.refresh_from_db()
        self.assertTrue(self.doc_a.check_password("NewPass123!"))

    def test_cannot_delete_other_clinic_cabinet(self):
        cab = Cabinet.objects.create(branch=self.ba, name="Каб А")
        self.client_for(self.dir_b).post(f"/users/cabinets/{cab.pk}/delete/")
        self.assertTrue(Cabinet.objects.filter(pk=cab.pk).exists())

    def test_quick_appointment_rejects_other_clinic_doctor(self):
        c = self.client_for(self.dir_b)
        p_b = Patient.all_objects.create(first_name="Б", last_name="Б", phone="+996700000803",
                                         branch=self.bb, clinic=self.b)
        r = c.post("/appointments/create-quick/", data=json.dumps({
            "doctor_id": self.doc_a.pk, "patient_id": p_b.pk,
            "start_at": (timezone.now() + timezone.timedelta(days=1)).isoformat(),
            "duration": 30,
        }), content_type="application/json")
        self.assertFalse(Appointment.all_objects.filter(doctor=self.doc_a).exists(), r.content[:200])

    def test_django_admin_login_goes_through_main_login(self):
        r = Client().get("/django-admin/login/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])


class SanitizeTestCase(TestCase):
    def test_external_names_lose_angle_brackets(self):
        c = Clinic.objects.create(slug="sec-s", name="S")
        b = Branch.objects.create(clinic=c, name="S1", address="-", phone="0", is_main=True)
        p = Patient.all_objects.create(first_name='<img src=x onerror="alert(1)">', last_name="<script>x</script>",
                                       phone="+996700000804", branch=b, clinic=c)
        p.refresh_from_db()
        self.assertNotIn("<", p.first_name + p.last_name)
        self.assertNotIn(">", p.first_name + p.last_name)


class StripNamesTestCase(TestCase):
    def test_strip_names_only_touches_name_keys_and_keeps_apostrophe(self):
        from apps.users.sanitize import strip_names
        data = {"patients": [{"fullName": "Ma'mura <b>\"x\"", "note": "<5 мм"}], "who": "`a`"}
        out = strip_names(data)
        self.assertEqual(out["patients"][0]["fullName"], "Ma'mura b”x”")
        self.assertEqual(out["patients"][0]["note"], "<5 мм")
        self.assertEqual(out["who"], "ʼaʼ")

    def test_json_middleware_cleans_names(self):
        from django.http import JsonResponse
        from django.test import RequestFactory
        from apps.users.sanitize import JsonNamesMiddleware
        mw = JsonNamesMiddleware(lambda r: JsonResponse({"name": "<img src=x onerror=alert(1)>", "body": "<ok>"}))
        resp = mw(RequestFactory().get("/new/patients/data/"))
        data = json.loads(resp.content)
        self.assertNotIn("<", data["name"])
        self.assertEqual(data["body"], "<ok>")
        sync = JsonNamesMiddleware(lambda r: JsonResponse({"name": "<x>"}))(RequestFactory().get("/sync/export/"))
        self.assertEqual(json.loads(sync.content)["name"], "<x>")


class ClientIpTestCase(TestCase):
    def test_forwarded_for_cannot_spoof_ip(self):
        from django.test import RequestFactory, override_settings
        from apps.tenancy import get_client_ip
        req = RequestFactory().get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6, 5.5.5.5",
                                   HTTP_X_REAL_IP="5.5.5.5")
        with override_settings(TRUST_X_REAL_IP=True):
            self.assertEqual(get_client_ip(req), "5.5.5.5")   # от nginx
        with override_settings(TRUST_X_REAL_IP=False):
            self.assertEqual(get_client_ip(req), "127.0.0.1")  # без прокси заголовкам не верим


class ProtectedMediaTestCase(TestCase):
    def setUp(self):
        import tempfile
        from django.core.files.base import ContentFile
        from django.test import override_settings
        from apps.treatments.models import Treatment, TreatmentFile
        self.tmp = tempfile.TemporaryDirectory()
        self._ov = override_settings(MEDIA_ROOT=self.tmp.name)
        self._ov.enable()
        self.a = Clinic.objects.create(slug="med-a", name="A")
        self.b = Clinic.objects.create(slug="med-b", name="B")
        ba = Branch.objects.create(clinic=self.a, name="A1", address="-", phone="0", is_main=True)
        director = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.ua = User.objects.create(login="med_a", name="A", clinic=self.a, role=director)
        self.ub = User.objects.create(login="med_b", name="B", clinic=self.b, role=director)
        p = Patient.all_objects.create(first_name="П", last_name="А", phone="+996700000901", branch=ba, clinic=self.a)
        t = Treatment.all_objects.create(patient=p, doctor=self.ua, branch=ba, clinic=self.a, status="completed")
        self.f = TreatmentFile(treatment=t, name="снимок")
        self.f.file.save("рентген 1.jpg", ContentFile(b"\xff\xd8JPEGDATA"), save=True)
        self.url = self.f.file.url

    def tearDown(self):
        self._ov.disable()
        self.tmp.cleanup()

    def test_anonymous_and_other_clinic_get_404(self):
        self.assertEqual(Client().get(self.url).status_code, 404)
        c = Client(); c.force_login(self.ub)
        self.assertEqual(c.get(self.url).status_code, 404)

    def test_own_clinic_gets_file(self):
        c = Client(); c.force_login(self.ua)
        r = c.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"\xff\xd8JPEGDATA")

    def test_signed_link_works_without_login_and_bad_signature_fails(self):
        from apps.users.media_views import signed_url
        su = signed_url(self.f.file.name)
        self.assertEqual(Client().get(su).status_code, 200)
        self.assertEqual(Client().get(self.url + "?s=forged").status_code, 404)

    def test_accel_redirect_header_and_traversal(self):
        from django.test import override_settings
        c = Client(); c.force_login(self.ua)
        with override_settings(MEDIA_ACCEL_REDIRECT=True):
            r = c.get(self.url)
        self.assertTrue(r["X-Accel-Redirect"].startswith("/protected-media/treatments/"))
        self.assertEqual(c.get("/media/treatments/../../config/settings/server.py").status_code, 404)


class WebhookSecretTestCase(TestCase):
    def test_webhooks_rejected_without_secret_on_server(self):
        from django.test import override_settings
        c = Clinic.objects.create(slug="wh-a", name="A")
        with override_settings(WEBHOOK_REQUIRE_SECRET=True, GREENAPI_WEBHOOK_KEY=""):
            r = Client().post("/notifications/wa-webhook/", data="{}", content_type="application/json")
            self.assertEqual(r.status_code, 403)
            r = Client().post(f"/notifications/tg-webhook/{c.slug}/", data="{}", content_type="application/json")
            self.assertEqual(r.status_code, 403)
        with override_settings(WEBHOOK_REQUIRE_SECRET=True, GREENAPI_WEBHOOK_KEY="k"):
            r = Client().post("/notifications/wa-webhook/?key=bad", data="{}", content_type="application/json")
            self.assertEqual(r.status_code, 403)
