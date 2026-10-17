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

    def test_patients_data_search_only_for_technician(self):
        """Отчёт безопасности №19: технику — только поиск пациента (2+ символа, ≤10 строк)."""
        clear_current_clinic()
        r = self.c.get("/new/patients/data/")
        self.assertEqual(r.json()["results"], [])
        r = self.c.get("/new/patients/data/?q=Ив&per_page=200")
        data = r.json()
        self.assertEqual(data["perPage"], 10)
        self.assertEqual([p["id"] for p in data["results"]], [self.patient.pk])

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
        d = r.context["real_data"]["labMy"]
        self.assertFalse(d["technician"]["linked"])
        self.assertEqual(d["orders"], [])
        self.assertTrue(d["technician"]["code"].startswith("T-"))

    def _other_clinic(self):
        """Клиника Б в ODONTIS: свой админ, свой врач, свой пациент, свой заказ."""
        set_current_clinic(self.other)
        role = lambda n: Role.objects.get(name=n, clinic__isnull=True)  # noqa: E731
        admin_b = User.objects.create(login="lab_admin_b", name="Админ Б", role=role("admin_main"), clinic=self.other)
        doc_b = User.objects.create(login="lab_doc_b", name="Врач Б", role=role("doctor"), clinic=self.other)
        branch = Branch.objects.create(name="ФБ", address="-", phone="0", is_main=True, clinic=self.other)
        pat = Patient.objects.create(first_name="Бека", last_name="Б", phone="+996555000444", clinic=self.other)
        svc = Service.objects.create(name="Мост", price=1, clinic=self.other)
        t = Treatment.objects.create(patient=pat, doctor=doc_b, branch=branch, status="completed")
        local_tech = Technician.objects.create(name="Местный техник Б")
        foreign = TechnicianTask.objects.create(technician=local_tech, treatment=t, patient=pat, service=svc,
                                                amount=7000, clinic=self.other)
        set_current_clinic(self.clinic)
        return admin_b, t, svc, pat, foreign

    def test_connect_by_code_and_clinic_switch(self):
        self.tech.user = self.tech_user
        self.tech.save()
        code = self.c.get("/new/lab/my/data/").json()["technician"]["code"]
        admin_b, t, svc, pat, foreign = self._other_clinic()
        b = Client()
        b.force_login(admin_b)
        self.assertIn("не найден", b.post("/new/lab/connect/", {"code": "T-AAAA-AAAA"}).json()["error"])
        r = b.post("/new/lab/connect/", {"code": code.lower().replace("-", "")[1:]})   # без «T-» и дефисов
        self.assertTrue(r.json()["ok"], r.content)
        self.assertIn("уже подключён", b.post("/new/lab/connect/", {"code": code}).json()["error"])
        tech_b = Technician.all_clinics.get(pk=r.json()["id"])
        self.assertEqual((tech_b.clinic_id, tech_b.user_id), (self.other.pk, self.tech_user.pk))
        self.assertTrue(Notification.objects.filter(user=self.tech_user, title__contains="подключила").exists())
        # клиника Б отправляет заказ подключённому технику
        set_current_clinic(self.other)
        order_b = TechnicianTask.objects.create(technician=tech_b, treatment=t, patient=pat, service=svc,
                                                amount=5000, clinic=self.other)
        set_current_clinic(self.clinic)
        d = self.c.get("/new/lab/my/data/").json()
        keys = {o["key"]: o["clinicName"] for o in d["orders"]}
        self.assertEqual(keys, {f"c{self.mine.pk}": "Лаб", f"c{order_b.pk}": "Чужая"})
        self.assertEqual({c["key"] for c in d["clinics"]}, {f"c{self.clinic.pk}", f"c{self.other.pk}"})
        self.assertEqual(len(d["pay"]["clinics"]), 2)
        # заказ клиники Б — меняет статус; заказ другого техника клиники Б — нет
        self.assertTrue(self.c.post(f"/new/lab/my/{order_b.pk}/status/", {"status": "in_progress"}).json()["ok"])
        self.assertEqual(self.c.post(f"/new/lab/my/{foreign.pk}/status/", {"status": "in_progress"}).status_code, 404)
        self.assertTrue(self.c.post(f"/new/lab/my/{order_b.pk}/status/", {"status": "ready"}).json()["ok"])
        doc_b = t.doctor
        n = Notification.objects.filter(user=doc_b, title__startswith="Работа готова").first()
        self.assertIsNotNone(n)
        self.assertEqual(n.clinic_id, self.other.pk)
        # админ клиники А не может привязать чужой логин и не видит заказов Б
        self.assertEqual(self.c.get("/new/lab/").status_code, 302)
        # техник отключился — заказы Б пропали
        self.assertTrue(self.c.post(f"/new/lab/my/leave/{tech_b.pk}/").json()["ok"])
        keys = [o["key"] for o in self.c.get("/new/lab/my/data/").json()["orders"]]
        self.assertEqual(keys, [f"c{self.mine.pk}"])
        # новый код — старый не работает
        new = self.c.post("/new/lab/my/code/new/").json()["code"]
        self.assertNotEqual(new, code)
        self.assertIn("не найден", b.post("/new/lab/connect/", {"code": code}).json()["error"])
        # чужой сотрудник (не админ) подключать не может
        d2 = Client()
        d2.force_login(self.doc)
        self.assertEqual(d2.post("/new/lab/connect/", {"code": new}).status_code, 403)

    def test_connect_throttled(self):
        from django.core.cache import cache
        cache.clear()
        a = Client()
        a.force_login(self.admin)
        for _ in range(10):
            a.post("/new/lab/connect/", {"code": "T-ZZZZ-ZZZZ"})
        self.assertEqual(a.post("/new/lab/connect/", {"code": "T-ZZZZ-ZZZZ"}).status_code, 429)
        cache.clear()

    def test_external_clinic_orders_private(self):
        from apps.technicians.models import ExternalOrder
        r = self.c.post("/new/lab/my/ext/clinic/save/", {"name": "Улыбка <b>", "phone": "0555"})
        cid = r.json()["id"]
        r = self.c.post("/new/lab/my/ext/order/save/", {"clinic_id": cid, "work": "Коронка", "tooth": "11",
                                                        "patient": "Петров", "amount": "4500", "expected": "2030-01-01"})
        o = r.json()["order"]
        self.assertEqual((o["clinicName"], o["status"], o["amount"]), ("Улыбка b", "transferred", 4500.0))
        oid = o["id"]
        self.assertTrue(self.c.post(f"/new/lab/my/ext/order/{oid}/status/", {"status": "installed"}).json()["ok"])
        self.assertTrue(self.c.post(f"/new/lab/my/ext/order/{oid}/paid/", {"paid": "1"}).json()["order"]["paid"])
        up = self.c.post(f"/new/lab/my/ext/order/{oid}/upload/",
                         {"file": SimpleUploadedFile("scan.stl", b"solid x", content_type="model/stl")}).json()
        url = up["order"]["files"][0]["url"]
        d = self.c.get("/new/lab/my/data/").json()
        row = [p for p in d["pay"]["clinics"] if p["key"] == f"x{cid}"][0]
        self.assertEqual((row["earnedMonth"], row["paidMonth"], row["unpaid"]), (4500.0, 4500.0, 0.0))
        # другой пользователь: ни заказа, ни файла (без подписи)
        other = Client()
        other.force_login(self.admin)
        self.assertEqual(other.post(f"/new/lab/my/ext/order/{oid}/status/", {"status": "ready"}).status_code, 404)
        self.assertEqual(other.post("/new/lab/my/ext/order/save/", {"clinic_id": cid, "work": "x"}).status_code, 400)
        path = url.split("?")[0]
        self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(self.c.get(path).status_code, 200)
        self.assertEqual(Client().get(url).status_code, 200)       # подписанная ссылка
        # клиника с заказами не удаляется, а прячется
        self.assertTrue(self.c.post(f"/new/lab/my/ext/clinic/{cid}/delete/").json()["ok"])
        self.assertTrue(ExternalOrder.objects.filter(pk=oid).exists())
        self.assertTrue(self.c.post(f"/new/lab/my/ext/order/{oid}/delete/").json()["ok"])
        self.assertFalse(ExternalOrder.objects.filter(pk=oid).exists())


    def test_comments_and_deadline_request(self):
        from datetime import timedelta as td
        from apps.technicians.models import TechnicianOrderMessage as M
        self.tech.user = self.tech_user
        self.tech.save()
        today = timezone.localdate()
        old_due = self.mine.expected_ready
        # техник пишет — врачу и админу уведомление
        r = self.c.post(f"/new/lab/my/{self.mine.pk}/comment/", {"text": "Нужен ещё слепок <b>"}).json()
        self.assertEqual(r["order"]["messages"][0]["text"], "Нужен ещё слепок b")
        for u in (self.doc, self.admin):
            n = Notification.objects.filter(user=u, title__startswith="Техник пишет").first()
            self.assertIsNotNone(n)
            self.assertEqual(n.link, f"/new/lab/?order={self.mine.pk}")
        # чужой заказ — нельзя
        self.assertEqual(self.c.post(f"/new/lab/my/{self.alien.pk}/comment/", {"text": "x"}).status_code, 404)
        # запрос срока: проверки
        url = f"/new/lab/my/{self.mine.pk}/deadline/"
        self.assertIn("не раньше", self.c.post(url, {"date": (today - td(days=1)).isoformat()}).json()["error"])
        self.assertIn("текущий", self.c.post(url, {"date": old_due.isoformat()}).json()["error"])
        new_due = today + td(days=9)
        r = self.c.post(url, {"date": new_due.isoformat(), "reason": "ждём циркон"}).json()
        self.assertTrue(r["ok"])
        self.assertIn("ждёт", self.c.post(url, {"date": (today + td(days=10)).isoformat()}).json()["error"])
        self.assertTrue(Notification.objects.filter(user=self.doc, title__startswith="Техник просит").exists())
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.expected_ready, old_due)          # пока клиника не решила — срок прежний
        # клиника: карточка, ответ, решение
        a = Client()
        a.force_login(self.admin)
        d = a.get(f"/new/lab/order/{self.mine.pk}/").json()["order"]
        mid = d["pendingDeadline"]
        self.assertIsNotNone(mid)
        a.post(f"/new/lab/order/{self.mine.pk}/comment/", {"text": "Хорошо"})
        self.assertTrue(Notification.objects.filter(user=self.tech_user, title__startswith="Клиника пишет").exists())
        d = a.post(f"/new/lab/order/{self.mine.pk}/deadline/{mid}/", {"approve": "1"}).json()["order"]
        self.assertIsNone(d["pendingDeadline"])
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.expected_ready, new_due)
        self.assertTrue(Notification.objects.filter(user=self.tech_user, title__startswith="Срок перенесён").exists())
        self.assertIn("решён", a.post(f"/new/lab/order/{self.mine.pk}/deadline/{mid}/", {"approve": "1"}).json()["error"])
        # отклонение
        self.c.post(url, {"date": (today + td(days=20)).isoformat()})
        mid2 = M.objects.get(task=self.mine, decision=M.PENDING).pk
        a.post(f"/new/lab/order/{self.mine.pk}/deadline/{mid2}/", {"approve": ""})
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.expected_ready, new_due)
        # техник не может решать сам и не видит карточку клиники
        self.assertEqual(self.c.get(f"/new/lab/order/{self.mine.pk}/").status_code, 302)
        self.assertEqual(self.c.post(f"/new/lab/order/{self.mine.pk}/deadline/{mid2}/", {"approve": "1"}).status_code, 403)
        lab = self.c.get("/new/lab/my/data/").json()["orders"][0]
        self.assertEqual([m["kind"] for m in lab["messages"]], ["comment", "deadline", "comment", "deadline"])

    def test_create_login_button(self):
        a = Client()
        a.force_login(self.admin)
        self.tech2.phone = "+998 90 533-16-33"
        self.tech2.save()
        r = a.post("/new/lab/create-login/", {"technician_id": self.tech2.pk}).json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["login"], "998905331633")
        self.assertEqual(len(r["password"]), 8)
        self.tech2.refresh_from_db()
        u = self.tech2.user
        self.assertTrue(u.is_technician_only)
        self.assertEqual((u.clinic_id, u.name), (self.clinic.pk, "Другой"))
        self.assertTrue(u.check_password(r["password"]))
        # повторно — нельзя; врач — нельзя
        self.assertIn("уже есть", a.post("/new/lab/create-login/", {"technician_id": self.tech2.pk}).json()["error"])
        d = Client()
        d.force_login(self.doc)
        self.assertEqual(d.post("/new/lab/create-login/", {"technician_id": self.tech.pk}).status_code, 403)
        # тот же телефон у другого техника — логин с суффиксом; без телефона — tech<id>
        self.tech.phone = "+998905331633"
        self.tech.save()
        self.assertEqual(a.post("/new/lab/create-login/", {"technician_id": self.tech.pk}).json()["login"],
                         "998905331633-2")
        t3 = Technician.objects.create(name="Без телефона", clinic=self.clinic)
        self.assertEqual(a.post("/new/lab/create-login/", {"technician_id": t3.pk}).json()["login"], f"tech{t3.pk}")
        # созданный техник входит и попадает в свой кабинет
        c = Client()
        self.assertTrue(c.login(login="998905331633", password=r["password"]))
        self.assertEqual(c.get("/new/").get("Location"), "/new/lab/my/")

    def test_new_ui_technician_card(self):
        from apps.technicians.models import TechnicianAgreement, TechnicianWarrantyCase
        a = Client()
        a.force_login(self.admin)
        r = a.get(f"/new/lab/tech/{self.tech.pk}/")
        self.assertEqual(r.status_code, 200)
        d = r.context["real_data"]["labTech"]
        self.assertEqual([o["id"] for o in d["orders"]], [self.mine.pk])
        # расценка: добавить, изменить, удалить
        url = f"/new/lab/tech/{self.tech.pk}/"
        d = a.post(url + "price/", {"service_id": self.crown.pk, "price": "3500"}).json()["tech"]
        self.assertEqual(d["prices"][0]["price"], 3500.0)
        d = a.post(url + "price/", {"service_id": self.crown.pk, "price": "4000"}).json()["tech"]
        self.assertEqual([p["price"] for p in d["prices"]], [4000.0])
        self.assertIn("цена", a.post(url + "price/", {"service_id": self.crown.pk, "price": "-5"}).json()["error"])
        aid = TechnicianAgreement.objects.get(technician=self.tech).pk
        self.assertEqual(a.post(url + f"price/{aid}/delete/").json()["tech"]["prices"], [])
        # правка карточки
        d = a.post(url + "edit/", {"name": "Асан Техник", "phone": "0555", "default_lead_days": "6",
                                   "specialization": "zirconia", "is_active": "on"}).json()["tech"]
        self.assertEqual((d["name"], d["leadDays"], d["specializationLabel"]), ("Асан Техник", 6, "Цирконий"))
        # гарантийный случай + отметка «решено»
        d = a.post(url + "warranty/", {"task_id": self.mine.pk, "reason": "скол"}).json()["tech"]
        self.assertEqual(d["warranty"][0]["order"], f"#L-{self.mine.pk:04d}")
        w = TechnicianWarrantyCase.objects.get(technician=self.tech)
        self.assertTrue(a.post(url + f"warranty/{w.pk}/resolve/").json()["tech"]["warranty"][0]["resolved"])
        # техник сам эту страницу не открывает
        self.assertEqual(self.c.get(url).get("Location"), "/new/lab/my/")


class LabFileCompressionTestCase(TestCase):
    """Фото, прикреплённые лаборантом, сжимаются; 3D-скан/PDF — как есть."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        self._media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        self._media.enable()

    def tearDown(self):
        self._media.disable()

    def test_photo_compressed_scan_kept(self):
        import io
        import os
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.technicians.models import ExternalClinic, ExternalOrder, ExternalOrderFile
        img = Image.effect_noise((4000, 3000), 80).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        big = buf.getvalue()
        owner = User.objects.create(login="lab_owner_cmp", name="Лаборант")
        ext = ExternalClinic.objects.create(owner=owner, name="Клиника")
        order = ExternalOrder.objects.create(owner=owner, clinic=ext)
        photo = ExternalOrderFile.objects.create(order=order, file=SimpleUploadedFile("slepok.png", big), name="slepok")
        self.assertTrue(photo.file.name.endswith(".jpg"))
        self.assertLess(os.path.getsize(photo.file.path), len(big))
        with Image.open(photo.file.path) as im:
            self.assertLessEqual(max(im.size), 2560)
        scan = ExternalOrderFile.objects.create(order=order, file=SimpleUploadedFile("jaw.stl", b"solid x\n" * 100000))
        self.assertTrue(scan.file.name.endswith(".stl"))
        self.assertEqual(os.path.getsize(scan.file.path), 800000)
