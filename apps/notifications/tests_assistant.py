import json
from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.users.models import User, Role, Clinic, Branch


def _tool_call(name, args, cid="c1"):
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _final(text):
    return {"choices": [{"message": {"content": text}}]}


@override_settings(OPENAI_API_KEY="sk-test", OPENAI_MODEL="gpt-test")
class AssistantTestCase(TestCase):
    """ИИ-помощник на OpenAI (сам OpenAI подменён): инструменты, запись
    пациента через подтверждение, зубы и услуги в карте приёма."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.services.models import Service
        from apps.tenancy import set_current_clinic
        self.clinic = Clinic.objects.create(name="Клиника ИИ", slug="ai-clinic")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Гл.", address="-", phone="0", is_main=True, clinic=self.clinic)
        admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        doc_role, _ = Role.objects.get_or_create(name=Role.DOCTOR)
        self.director = User.objects.create(login="ai_dir", name="Директор", role=admin_role, clinic=self.clinic)
        self.doctor = User.objects.create(login="ai_doc", name="Каримов Алишер", role=doc_role, clinic=self.clinic)
        self.doctor.branches.add(self.branch)
        self.patient = Patient.objects.create(first_name="Нилуфар", last_name="Сатторова",
                                              phone="+998901112233", clinic=self.clinic)
        self.filling = Service.objects.create(name="Пломба композитная", price=300000, duration=60, clinic=self.clinic)
        self.extract = Service.objects.create(name="Удаление зуба простое", price=150000, duration=30, clinic=self.clinic)
        self.client = Client()
        self.client.force_login(self.director)
        self.tomorrow = timezone.localdate() + timedelta(days=1)

    def tearDown(self):
        from apps.tenancy import clear_current_clinic
        clear_current_clinic()

    def _ask(self, text, replies, page=None, history=None):
        calls = []

        def fake(path, data, **kw):
            calls.append((path, json.loads(json.dumps(data, default=str))))
            return replies.pop(0), None
        with patch("apps.notifications.assistant._request", side_effect=fake):
            resp = self.client.post("/notifications/voice/", {
                "mode": "agent", "question": text, "page": json.dumps(page or {}),
                "history": json.dumps(history or [])})
        return resp, calls

    def test_book_patient_needs_confirmation_then_creates_appointment(self):
        from apps.appointments.models import Appointment
        start = "%sT10:00" % self.tomorrow.isoformat()
        resp, calls = self._ask("Запиши Сатторову к Каримову завтра на 10", [
            _tool_call("search_patients", {"query": "901112233"}),
            _tool_call("free_slots", {"doctor_id": self.doctor.pk, "date": self.tomorrow.isoformat()}),
            _tool_call("propose_appointment", {"patient_id": self.patient.pk, "doctor_id": self.doctor.pk,
                                               "start": start, "service_ids": [self.filling.pk]}),
            _final("Подготовил запись Сатторовой к Каримову завтра в 10:00, подтвердите."),
        ])
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("подтвердите", data["answer"])
        # результаты инструментов ушли модели: пациент найден, 10:00 свободно
        tool_msgs = [m for m in calls[-1][1]["messages"] if m["role"] == "tool"]
        self.assertIn("Сатторова", tool_msgs[0]["content"])
        self.assertIn("10:00", tool_msgs[1]["content"])
        self.assertEqual(calls[0][1]["model"], "gpt-test")
        # пока не подтвердили — записи нет
        self.assertFalse(Appointment.objects.exists())
        action = data["actions"][0]
        self.assertEqual(action["type"], "confirm_appointment")
        with patch("apps.appointments.views.notify_appointment_created"):
            r2 = self.client.post("/notifications/assistant/confirm/", {"token": action["token"]})
        self.assertEqual(r2.status_code, 200, r2.content)
        appt = Appointment.objects.get()
        self.assertEqual((appt.patient, appt.doctor), (self.patient, self.doctor))
        self.assertEqual(timezone.localtime(appt.start_at).hour, 10)
        self.assertEqual(appt.end_at - appt.start_at, timedelta(minutes=60))
        self.assertEqual(list(appt.services.all()), [self.filling])
        # повторное подтверждение — время уже занято
        r3 = self.client.post("/notifications/assistant/confirm/", {"token": action["token"]})
        self.assertEqual(r3.status_code, 400)

    def test_new_patient_and_busy_time(self):
        from apps.appointments.models import Appointment
        from apps.patients.models import Patient
        busy = timezone.make_aware(datetime.combine(self.tomorrow, time(11, 0)))
        Appointment.objects.create(patient=self.patient, doctor=self.doctor, branch=self.branch,
                                   start_at=busy, end_at=busy + timedelta(hours=1), clinic=self.clinic)
        resp, calls = self._ask("Запиши нового", [
            _tool_call("propose_appointment", {"new_patient_name": "Иванов Пётр", "new_patient_phone": "+998901234567",
                                               "doctor_id": self.doctor.pk, "start": "%sT11:00" % self.tomorrow}),
            _tool_call("propose_appointment", {"new_patient_name": "Иванов Пётр", "new_patient_phone": "+998901234567",
                                               "doctor_id": self.doctor.pk, "start": "%sT13:00" % self.tomorrow}, "c2"),
            _final("Подготовил на 13:00."),
        ])
        msgs = calls[1][1]["messages"]
        self.assertIn("уже есть запись", msgs[-1]["content"])   # занятое время — ошибка модели
        token = resp.json()["actions"][0]["token"]
        with patch("apps.appointments.views.notify_appointment_created"):
            self.client.post("/notifications/assistant/confirm/", {"token": token})
        p = Patient.objects.get(phone="+998901234567")
        self.assertEqual((p.last_name, p.first_name), ("Иванов", "Пётр"))

    def test_confirm_token_is_personal(self):
        from apps.notifications.assistant import CONFIRM_SALT
        from django.core import signing
        token = signing.dumps({"u": self.doctor.pk, "d": self.doctor.pk, "s": "%sT10:00" % self.tomorrow,
                               "m": 60, "p": self.patient.pk}, salt=CONFIRM_SALT)
        r = self.client.post("/notifications/assistant/confirm/", {"token": token})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/notifications/assistant/confirm/", {"token": "garbage"})
        self.assertEqual(r.status_code, 400)

    def test_visit_card_teeth_and_services(self):
        from apps.treatments.models import Treatment
        tr = Treatment.objects.create(patient=self.patient, doctor=self.doctor, branch=self.branch, clinic=self.clinic)
        page = {"type": "visit", "treatment_id": tr.pk}
        resp, calls = self._ask("36 композитная пломба, 47 удаление", [
            _tool_call("search_services", {"query": "пломба композитная"}),
            _tool_call("add_to_visit", {"items": [
                {"teeth": [36], "service_id": self.filling.pk},
                {"teeth": [47, 99], "service_id": self.extract.pk, "discount_pct": 10}]}),
            _final("Добавил: 36 — пломба, 47 — удаление."),
        ], page=page)
        self.assertIn("КАРТА ПРИЁМА", calls[0][1]["messages"][0]["content"])
        self.assertIn("Пломба композитная", calls[1][1]["messages"][-1]["content"])
        action = resp.json()["actions"][0]
        self.assertEqual(action["type"], "visit_add")
        self.assertEqual(action["items"][0]["teeth"], [36])
        self.assertEqual(action["items"][1]["teeth"], [47])     # 99 — не зуб
        self.assertEqual(action["items"][1]["discount_pct"], 10)

    def test_add_to_visit_outside_visit_card_is_refused(self):
        resp, calls = self._ask("36 пломба", [
            _tool_call("add_to_visit", {"items": [{"teeth": [36], "service_id": self.filling.pk}]}),
            _final("Откройте приём пациента."),
        ])
        self.assertEqual(resp.json()["actions"], [])
        self.assertIn("Карта приёма не открыта", calls[1][1]["messages"][-1]["content"])

    def test_finance_hidden_from_doctor(self):
        self.client.force_login(self.doctor)
        resp, calls = self._ask("Какая выручка?", [_tool_call("clinic_finance", {}), _final("Нет доступа.")])
        self.assertIn("Нет доступа", calls[1][1]["messages"][-1]["content"])

    def test_model_fallback_when_configured_model_missing(self):
        from apps.notifications import assistant
        seen = []

        def fake(path, data, **kw):
            seen.append(data["model"])
            if data["model"] == "gpt-test":
                return None, (404, "The model `gpt-test` does not exist")
            return _final("Привет"), None
        with patch("apps.notifications.assistant._request", side_effect=fake):
            answer, err = assistant.simple_answer("Привет")
        self.assertEqual((answer, err), ("Привет", None))
        self.assertEqual(seen[:2], ["gpt-test", "gpt-4.1-mini"])

    def test_free_slots_respects_busy_and_schedule(self):
        from apps.appointments.models import Appointment
        from apps.notifications.assistant import free_slots
        busy = timezone.make_aware(datetime.combine(self.tomorrow, time(10, 0)))
        Appointment.objects.create(patient=self.patient, doctor=self.doctor, branch=self.branch,
                                   start_at=busy, end_at=busy + timedelta(minutes=30), clinic=self.clinic)
        slots = free_slots(self.doctor, self.tomorrow, 60)
        self.assertNotIn("10:00", slots)
        self.assertNotIn("09:30", slots)
        self.assertIn("10:30", slots)

    def test_voice_uses_openai_transcription(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        with patch("apps.notifications.assistant._request", return_value=({"text": "зуб 36"}, None)) as m, \
                patch("apps.notifications.voice._get_whisper_model") as whisper:
            resp = self.client.post("/notifications/voice/", {
                "mode": "dictate", "audio": SimpleUploadedFile("v.webm", b"123", "audio/webm")})
        self.assertEqual(resp.json()["transcript"], "зуб 36")
        self.assertEqual(m.call_args[0][0], "/audio/transcriptions")
        whisper.assert_not_called()   # локальная модель не грузится в память сервера

    def test_speak_uses_openai(self):
        with patch("apps.notifications.assistant._request", return_value=(b"OggS", None)) as m:
            resp = self.client.post("/notifications/voice/speak/", {"text": "Готово"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"OggS")
        self.assertEqual(m.call_args[0][0], "/audio/speech")

    def test_agent_disabled_without_key(self):
        with self.settings(OPENAI_API_KEY=""):
            resp = self.client.post("/notifications/voice/", {"mode": "agent", "question": "привет"})
        self.assertEqual(resp.status_code, 503)
