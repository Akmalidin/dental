import json
from decimal import Decimal
from django.test import TestCase, Client
from apps.users.models import User, Branch, Clinic, Role
from apps.patients.models import Patient
from apps.treatments.models import Treatment
from apps.treatments.forms import TreatmentForm
from apps.tenancy import set_current_clinic, clear_current_clinic


class TreatmentNumberTestCase(TestCase):
    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника A", slug="clinic-a")
        self.clinic_b = Clinic.objects.create(name="Клиника B", slug="clinic-b")
        self.branch_a = Branch.objects.create(name="A", address="-", phone="0", is_main=True, clinic=self.clinic_a)
        self.branch_b = Branch.objects.create(name="B", address="-", phone="0", is_main=True, clinic=self.clinic_b)
        self.doctor_a = User.objects.create(login="doc_a", name="Врач A", email="a@test.local", clinic=self.clinic_a)
        self.doctor_b = User.objects.create(login="doc_b", name="Врач B", email="b@test.local", clinic=self.clinic_b)
        self.patient_a = Patient.objects.create(
            first_name="Пац", last_name="A", phone="1", branch=self.branch_a, clinic=self.clinic_a
        )
        self.patient_b = Patient.objects.create(
            first_name="Пац", last_name="B", phone="2", branch=self.branch_b, clinic=self.clinic_b
        )

    def _make_treatment(self, clinic, branch, doctor, patient):
        return Treatment.objects.create(
            patient=patient, doctor=doctor, branch=branch, clinic=clinic,
        )

    def test_numbering_starts_at_one_per_clinic(self):
        t1 = self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        t2 = self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        self.assertEqual(t1.number, 1)
        self.assertEqual(t2.number, 2)

    def test_numbering_independent_across_clinics(self):
        self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        t_b1 = self._make_treatment(self.clinic_b, self.branch_b, self.doctor_b, self.patient_b)
        self.assertEqual(t_b1.number, 1)  # клиника B не видит нумерацию клиники A

    def test_display_number_falls_back_to_pk_when_number_missing(self):
        t = self._make_treatment(self.clinic_a, self.branch_a, self.doctor_a, self.patient_a)
        Treatment.all_objects.filter(pk=t.pk).update(number=None)
        t.refresh_from_db()
        self.assertEqual(t.display_number, t.pk)


class TreatmentFormClinicIsolationTestCase(TestCase):
    """Regression test: patient field must never leak patients from other clinics
    into the treatment form's dropdown (same class of bug as AppointmentForm —
    ModelForm base_fields queryset frozen, unfiltered, at module-import time)."""

    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника C", slug="clinic-a-tf")
        self.clinic_b = Clinic.objects.create(name="Клиника D", slug="clinic-b-tf")
        self.branch_a = Branch.objects.create(name="A", address="-", phone="0", is_main=True, clinic=self.clinic_a)
        self.branch_b = Branch.objects.create(name="B", address="-", phone="0", is_main=True, clinic=self.clinic_b)
        self.patient_a = Patient.objects.create(
            first_name="Пац", last_name="A", phone="3", branch=self.branch_a, clinic=self.clinic_a
        )
        self.patient_b = Patient.objects.create(
            first_name="Пац", last_name="B", phone="4", branch=self.branch_b, clinic=self.clinic_b
        )

    def tearDown(self):
        clear_current_clinic()

    def test_patient_field_scoped_to_current_clinic(self):
        set_current_clinic(self.clinic_a)
        form = TreatmentForm()
        patient_ids = set(form.fields["patient"].queryset.values_list("pk", flat=True))
        self.assertIn(self.patient_a.pk, patient_ids)
        self.assertNotIn(self.patient_b.pk, patient_ids)


class _VisitWizardTestBase(TestCase):
    """Общий сетап для мастера приёма — старый и новый интерфейс бьют в один
    и тот же бэкенд (views_visit.py), поэтому оба покрываются от одних данных."""

    def setUp(self):
        from apps.services.models import Service
        from apps.appointments.models import Appointment
        from django.utils import timezone
        import datetime as dt

        self.clinic = Clinic.objects.create(name="Клиника VW", slug="clinic-visit-wizard")
        self.branch = Branch.objects.create(name="Филиал VW", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(
            login="vw_director", name="Директор VW", email="vwd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.doctor = User.objects.create(
            login="vw_doctor", name="Врач VW", email="vwdoc@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.patient = Patient.objects.create(
            first_name="Приём", last_name="Тестов", phone="+996700321321", branch=self.branch, clinic=self.clinic,
        )
        self.service = Service.objects.create(name="Пломбирование", price=2500, duration=30, clinic=self.clinic)
        today = timezone.localdate()
        start = timezone.make_aware(dt.datetime.combine(today, dt.time(11, 0)))
        end = timezone.make_aware(dt.datetime.combine(today, dt.time(11, 30)))
        self.appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch, service=self.service,
            start_at=start, end_at=end, status=Appointment.STATUS_ARRIVED, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)


class VisitWizardOldInterfaceTestCase(_VisitWizardTestBase):
    """Старый интерфейс (/treatments/visit/...) — регрессия после вынесения
    общей _visit_wizard_context()/_resolve_or_create_visit() для нового интерфейса."""

    def test_visit_start_creates_treatment_moves_appointment_to_in_progress(self):
        resp = self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        self.assertRedirects(resp, f"/treatments/visit/{treatment.pk}/")
        self.assertEqual(treatment.status, Treatment.STATUS_IN_PROGRESS)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "in_progress")

    def test_visit_start_does_not_duplicate_treatment_on_repeat(self):
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        self.assertEqual(Treatment.objects.filter(appointment=self.appt).count(), 1)

    def test_visit_wizard_page_renders(self):
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.get(f"/treatments/visit/{treatment.pk}/")
        self.assertEqual(resp.status_code, 200)

    def test_visit_save_persists_emr_fields_and_teeth(self):
        from apps.treatments.models_teeth import ToothCondition
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        # реальный пользователь всегда сначала открывает страницу мастера —
        # она сеет справочник ToothStatus (_ensure_tooth_statuses), без этого
        # шага сохранённому состоянию зуба не с чем сопоставить статус.
        self.client.get(f"/treatments/visit/{treatment.pk}/")
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/save/",
            data=json.dumps({"complaints": "Болит зуб 26", "diagnosis": "Кариес", "teeth": {"26": "caries"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        treatment.refresh_from_db()
        self.assertEqual(treatment.emr.complaints, "Болит зуб 26")
        tc = ToothCondition.objects.get(patient=self.patient, tooth_number=26)
        self.assertEqual(tc.status.code, "caries")

    def test_visit_commit_completes_treatment_and_creates_cure(self):
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/commit/",
            data=json.dumps({"plan": [{"service_id": self.service.pk, "tooth": "26", "qty": 1, "price": 2500, "done": True}]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        treatment.refresh_from_db()
        self.assertEqual(treatment.status, Treatment.STATUS_COMPLETED)
        self.assertEqual(treatment.cures.count(), 1)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "completed")

    def test_completed_treatment_redirects_away_from_wizard(self):
        self.client.get(f"/treatments/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        treatment.status = Treatment.STATUS_COMPLETED
        treatment.save(update_fields=["status"])
        resp = self.client.get(f"/treatments/visit/{treatment.pk}/")
        self.assertRedirects(resp, f"/treatments/{treatment.pk}/")


class NewUIVisitWizardTestCase(_VisitWizardTestBase):
    """Новый интерфейс (/new/visit/start/, /new/visitcard/<pk>/) — тот же
    бэкенд (save/upload/commit), что и старый, просто другой вход/страница."""

    def test_newui_visit_start_creates_treatment_and_redirects_to_new_visitcard(self):
        resp = self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        self.assertRedirects(resp, f"/new/visitcard/{treatment.pk}/")
        self.assertEqual(treatment.status, Treatment.STATUS_IN_PROGRESS)

    def test_newui_visit_start_resumes_same_treatment_as_old_interface_would(self):
        """Начать через новый интерфейс, затем «продолжить» тем же URL — не плодит дубли,
        та же дедупликация, что и у старого /treatments/visit/start/."""
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        self.assertEqual(Treatment.objects.filter(appointment=self.appt).count(), 1)

    def test_newui_visitcard_renders_real_data(self):
        import re
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.get(f"/new/visitcard/{treatment.pk}/")
        self.assertEqual(resp.status_code, 200)
        m = re.search(
            r'<script id="newui-real-data" type="application/json">(.*?)</script>',
            resp.content.decode(), re.DOTALL,
        )
        data = json.loads(m.group(1))
        vw = data["visitWizard"]
        self.assertEqual(vw["patientName"], "Тестов Приём")
        self.assertEqual(vw["treatmentId"], treatment.pk)
        self.assertEqual(vw["status"], "in_progress")

    def test_newui_visit_notes_field_persists_via_shared_save_endpoint(self):
        """Расширение visit_save под поле "Прочее" (Treatment.notes) — только для
        нового интерфейса, но не должно ломать старый (он это поле не шлёт)."""
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/save/",
            data=json.dumps({"notes": "Пациент нервничает"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        treatment.refresh_from_db()
        self.assertEqual(treatment.notes, "Пациент нервничает")

    def test_newui_visit_commit_completes_treatment(self):
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/commit/",
            data=json.dumps({"plan": [{"service_id": self.service.pk, "tooth": "14", "qty": 1, "price": 2500, "done": True}]}),
            content_type="application/json",
        )
        self.assertTrue(resp.json()["ok"])
        treatment.refresh_from_db()
        self.assertEqual(treatment.status, Treatment.STATUS_COMPLETED)

    def test_newui_visit_start_no_patient_redirects_to_schedule(self):
        resp = self.client.get("/new/visit/start/")
        self.assertRedirects(resp, "/new/schedule/")


class PhotoCompressionTestCase(TestCase):
    """Фото (до/после, полость рта, лицо, другое) сжимаются при загрузке до
    2560 px JPEG; рентген/ОПТГ/КЛКТ/прицельный и документы — в оригинале."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        self._tmp = tempfile.mkdtemp()
        self._ovr = override_settings(MEDIA_ROOT=self._tmp)
        self._ovr.enable()
        self.clinic = Clinic.objects.create(name="Клиника Фото", slug="photo-compress")
        set_current_clinic(self.clinic)
        self.patient = Patient.objects.create(first_name="Фото", last_name="Тест", phone="+996700000777", clinic=self.clinic)

    def tearDown(self):
        import shutil
        self._ovr.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)
        clear_current_clinic()

    def _jpeg(self, w=4000, h=3000, name="IMG_0001.JPG"):
        import io, random
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        rnd = random.Random(1)
        img = Image.effect_noise((w // 8, h // 8), 60).resize((w, h)).convert("RGB")
        img.putpixel((0, 0), (rnd.randrange(255), 0, 0))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=98)
        return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")

    def _create(self, f, kind):
        from apps.treatments.models import TreatmentFile
        return TreatmentFile.objects.create(patient=self.patient, file=f, kind=kind, name=f.name)

    def test_photo_is_resized_and_smaller(self):
        from PIL import Image
        f = self._jpeg()
        original = len(f.read()); f.seek(0)
        obj = self._create(f, "before")
        obj.file.open("rb")
        with Image.open(obj.file) as im:
            self.assertEqual(max(im.size), 2560)
            self.assertEqual(im.format, "JPEG")
        self.assertLess(obj.file.size, original)
        self.assertTrue(obj.file.name.endswith(".jpg"))
        self.assertEqual(obj.name, "IMG_0001.JPG")

    def test_xray_kinds_and_documents_keep_original(self):
        for kind in ("xray", "opg", "cbct", "intraoral", "document"):
            f = self._jpeg(name="%s.jpg" % kind)
            data = f.read(); f.seek(0)
            obj = self._create(f, kind)
            obj.file.open("rb")
            self.assertEqual(obj.file.read(), data, kind)

    def test_non_image_photo_kind_saved_as_is(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pdf = SimpleUploadedFile("scan.pdf", b"%PDF-1.4 fake" * 50000, content_type="application/pdf")
        obj = self._create(pdf, "other")
        obj.file.open("rb")
        self.assertTrue(obj.file.read().startswith(b"%PDF-1.4"))
        self.assertTrue(obj.file.name.endswith(".pdf"))

    def test_small_photo_untouched(self):
        f = self._jpeg(800, 600, name="small.jpg")
        data = f.read(); f.seek(0)
        self.assertLess(len(data), 400 * 1024)
        obj = self._create(f, "photo_oral")
        obj.file.open("rb")
        self.assertEqual(obj.file.read(), data)

    def test_exif_orientation_applied(self):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        img = Image.effect_noise((400, 300), 60).resize((4000, 3000)).convert("RGB")
        exif = Image.Exif(); exif[0x0112] = 6  # «повернуть на 90°» — так телефон сохраняет вертикальное фото
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=98, exif=exif)
        obj = self._create(SimpleUploadedFile("v.jpg", buf.getvalue()), "photo_face")
        obj.file.open("rb")
        with Image.open(obj.file) as im:
            self.assertEqual(im.size, (1920, 2560))


class TreatmentPlanByTeethTestCase(TestCase):
    """План лечения по зубной формуле: добавление услуги на выбранные зубы,
    печатная форма с группировкой по зубам и подписями, доступ только к
    планам своей клиники, кнопка «План лечения» из карточки приёма."""

    def setUp(self):
        from apps.services.models import Service, ServiceCategory
        from apps.treatments.models_plan import TreatmentPlan
        self.clinic = Clinic.objects.create(name="Клиника План", slug="plan-teeth")
        self.other = Clinic.objects.create(name="Чужая", slug="plan-teeth-other")
        role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.user = User.objects.create(login="pt_dir", name="Директор", role=role, clinic=self.clinic)
        self.other_user = User.objects.create(login="pt_other", name="Чужой", role=role, clinic=self.other)
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Ф", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.patient = Patient.objects.create(first_name="Мерием", last_name="Мазаева", phone="+996555000111", clinic=self.clinic)
        cat = ServiceCategory.objects.create(name="Ортопедия", clinic=self.clinic)
        self.crown = Service.objects.create(name="Циркониевая коронка", price=14000, category=cat, clinic=self.clinic)
        self.clean = Service.objects.create(name="Обезболивание", price=500, clinic=self.clinic)
        self.plan = TreatmentPlan.objects.create(patient=self.patient, doctor=self.user, title="План")
        clear_current_clinic()
        self.c = Client(); self.c.force_login(self.user)

    def tearDown(self):
        clear_current_clinic()

    def _bulk(self, client, **body):
        return client.post(f"/treatments/plans/{self.plan.pk}/items/bulk-add/", data=json.dumps(body),
                           content_type="application/json")

    def test_bulk_add_one_item_per_tooth_and_creates_stage(self):
        r = self._bulk(self.c, service_id=self.crown.pk, teeth=["26", "11", "26", "99", "x"], qty=1)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["added"], 2)
        items = list(self.plan.items.order_by("tooth_number").values_list("tooth_number", "price"))
        self.assertEqual([t for t, _ in items], ["11", "26"])
        self.assertEqual(self.plan.stages.count(), 1)
        self.assertEqual(len(data["plan"]["stages"][0]["items"]), 2)
        self.assertTrue(any(c["name"] == "Ортопедия" for c in data["plan"]["categories"]))

    def test_bulk_add_without_teeth_is_general_item(self):
        self._bulk(self.c, service_id=self.clean.pk, teeth=[], qty=2)
        it = self.plan.items.get()
        self.assertEqual((it.tooth_number, it.quantity), ("", 2))

    def test_other_clinic_cannot_touch_plan(self):
        other = Client(); other.force_login(self.other_user)
        self.assertEqual(self._bulk(other, service_id=self.crown.pk, teeth=["26"]).status_code, 404)
        self.assertEqual(other.get(f"/treatments/plans/{self.plan.pk}/print/").status_code, 404)
        self._bulk(self.c, service_id=self.crown.pk, teeth=["26"])
        item = self.plan.items.get()
        self.assertEqual(other.post(f"/treatments/plans/items/{item.pk}/toggle/").status_code, 404)
        self.assertEqual(other.post(f"/treatments/plans/items/{item.pk}/delete/").status_code, 404)
        self.assertTrue(self.plan.items.filter(pk=item.pk).exists())

    def test_print_groups_by_tooth_with_totals_and_signatures(self):
        self._bulk(self.c, service_id=self.crown.pk, teeth=["26", "11"])
        self._bulk(self.c, service_id=self.clean.pk, teeth=["26"])
        self._bulk(self.c, service_id=self.clean.pk, teeth=[])
        item = self.plan.items.filter(tooth_number="11").first()
        self.c.post(f"/treatments/plans/items/{item.pk}/toggle/")
        html = self.c.get(f"/treatments/plans/{self.plan.pk}/print/").content.decode()
        self.assertIn("ПЛАН ЛЕЧЕНИЯ (ПРЕДВАРИТЕЛЬНЫЙ)", html)
        self.assertLess(html.index("Зуб 11"), html.index("Зуб 26"))
        self.assertLess(html.index("Зуб 26"), html.index("Общие услуги"))
        self.assertIn("Итого по зубу 26: 14 500", html)
        self.assertIn("29 000", html)  # 14000*2 + 500*2
        self.assertIn("1 из 4", html)
        self.assertIn("ознакомлен(а) и согласен(на)", html)
        self.assertIn("является предварительной", html)

    def test_print_uses_clinic_note_template(self):
        from apps.settings_clinic.models_documents import DocumentTemplate
        set_current_clinic(self.clinic)
        DocumentTemplate.objects.create(name="Текст", doc_type="plan_note", clinic=self.clinic,
                                        content="Уважаемый(ая) {{patient_name}}, итого {{total}}.")
        clear_current_clinic()
        self._bulk(self.c, service_id=self.crown.pk, teeth=["26"])
        html = self.c.get(f"/treatments/plans/{self.plan.pk}/print/").content.decode()
        self.assertIn("Уважаемый(ая) Мазаева Мерием, итого 14 000", html)
        self.assertNotIn("является предварительной", html)

    def test_visit_plan_button_opens_existing_or_creates(self):
        from apps.treatments.models_plan import TreatmentPlan
        r = self.c.post(f"/new/patients/{self.patient.pk}/plan/")
        self.assertRedirects(r, f"/new/treatplans/{self.plan.pk}/", fetch_redirect_response=False)
        TreatmentPlan.objects.filter(pk=self.plan.pk).update(status="completed")
        r = self.c.post(f"/new/patients/{self.patient.pk}/plan/")
        new = TreatmentPlan.objects.exclude(pk=self.plan.pk).get()
        self.assertEqual((new.patient_id, new.status), (self.patient.pk, "draft"))
        self.assertRedirects(r, f"/new/treatplans/{new.pk}/", fetch_redirect_response=False)
        other = Client(); other.force_login(self.other_user)
        self.assertEqual(other.post(f"/new/patients/{self.patient.pk}/plan/").status_code, 404)
