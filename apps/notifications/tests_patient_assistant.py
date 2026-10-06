import json
from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.settings_clinic.models import ClinicSettings
from apps.users.models import User, Role, Clinic, Branch


def _tool_call(name, args, cid="c1"):
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _final(text):
    return {"choices": [{"message": {"content": text}}]}


@override_settings(OPENAI_API_KEY="sk-test", OPENAI_MODEL="gpt-test")
class PatientAssistantTestCase(TestCase):
    """ИИ-ассистент для пациентов в WhatsApp/Telegram (OpenAI подменён)."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.services.models import Service
        from apps.tenancy import set_current_clinic
        self.clinic = Clinic.objects.create(name="Клиника П", slug="pa-clinic")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Гл.", address="ул. Ленина 1", phone="0", is_main=True, clinic=self.clinic)
        self.cs, _ = ClinicSettings.objects.update_or_create(clinic=self.clinic, defaults={
            "name": self.clinic.name, "ai_patient_bot": True, "ai_patient_delay_min": 5,
            "ai_patient_since": timezone.now() - timedelta(days=1)})
        admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        doc_role, _ = Role.objects.get_or_create(name=Role.DOCTOR)
        self.admin = User.objects.create(login="pa_adm", name="Админ", role=admin_role, clinic=self.clinic)
        self.doctor = User.objects.create(login="pa_doc", name="Хожибек", role=doc_role, clinic=self.clinic)
        self.doctor.branches.add(self.branch)
        self.patient = Patient.objects.create(first_name="Нилуфар", last_name="Сатторова", phone="+998901112233",
                                              clinic=self.clinic, telegram_chat_id=777)
        self.svc = Service.objects.create(name="Чистка", price=200000, duration=60, clinic=self.clinic)
        self.tomorrow = timezone.localdate() + timedelta(days=1)
        self.noon = timezone.make_aware(datetime.combine(timezone.localdate(), time(12, 0)))
        self.sent = []

    def tearDown(self):
        from apps.tenancy import clear_current_clinic
        clear_current_clinic()

    def _in(self, body, phone="998907776655", channel="wa", ago=10, patient=None):
        from apps.notifications.models import WaMessage
        m = WaMessage.objects.create(patient=patient, direction="in", channel=channel, phone=phone, body=body,
                                     clinic=self.clinic, read=False)
        WaMessage.objects.filter(pk=m.pk).update(created_at=self.noon - timedelta(minutes=ago))
        return m

    def _tick(self, replies, now=None):
        from apps.notifications.patient_assistant import tick_clinic
        calls = []

        def fake(path, data, **kw):
            calls.append(json.loads(json.dumps(data, default=str)))
            return replies.pop(0), None

        def wa_send(phone, text):
            self.sent.append(("wa", phone, text))
            return True

        def tg_send(chat_id, text, buttons=None):
            self.sent.append(("tg", chat_id, text))
            return True
        with patch("apps.notifications.assistant._request", side_effect=fake), \
                patch("apps.notifications.whatsapp.wa_send_text", side_effect=wa_send), \
                patch("apps.notifications.telegram.tg_send_text", side_effect=tg_send), \
                patch("apps.appointments.views.notify_appointment_created"):
            n = tick_clinic(self.clinic, now=now or self.noon)
        return n, calls

    def test_new_whatsapp_patient_books_after_yes(self):
        from apps.appointments.models import Appointment
        from apps.notifications.models import Notification, WaMessage
        from apps.patients.models import Patient
        m = self._in("Хочу на чистку завтра в 10, меня зовут Иванов Пётр")
        start = "%sT10:00" % self.tomorrow.isoformat()
        n, calls = self._tick([
            _tool_call("free_slots", {"doctor_id": self.doctor.pk, "date": self.tomorrow.isoformat()}),
            _tool_call("book_appointment", {"doctor_id": self.doctor.pk, "start": start,
                                            "service_ids": [self.svc.pk], "full_name": "Иванов Пётр"}, "c2"),
            _final("Записал вас к Хожибеку на завтра в 10:00, ждём! Адрес: ул. Ленина 1."),
        ])
        self.assertEqual(n, 1)
        p = Patient.objects.get(last_name="Иванов")
        self.assertEqual(p.first_name, "Пётр")
        a = Appointment.objects.get(patient=p)
        self.assertEqual((a.doctor, a.source), (self.doctor, "whatsapp"))
        self.assertEqual(timezone.localtime(a.start_at).hour, 10)
        self.assertEqual(self.sent[0][:2], ("wa", "998907776655"))
        out = WaMessage.objects.get(direction="out")
        self.assertTrue(out.by_ai)
        self.assertEqual(out.patient, p)
        m.refresh_from_db()
        self.assertEqual(m.ai_status, "done")
        self.assertEqual(m.patient, p)
        self.assertTrue(Notification.objects.filter(user=self.admin, title__contains="Ассистент").exists())
        sysmsg = calls[0]["messages"][0]["content"]
        self.assertIn("ещё не найден", sysmsg)
        self.assertEqual(calls[0]["messages"][1]["content"], "Хочу на чистку завтра в 10, меня зовут Иванов Пётр")
        # второй тик — ответ уже дан, OpenAI не вызывается
        n2, calls2 = self._tick([])
        self.assertEqual((n2, calls2), (0, []))

    def test_waits_for_admin_during_work_hours_but_answers_at_night(self):
        self._in("Здравствуйте", ago=2)
        n, calls = self._tick([])
        self.assertEqual((n, calls), (0, []))          # 2 минуты — админ ещё может ответить
        night = timezone.make_aware(datetime.combine(timezone.localdate(), time(23, 30)))
        self._in("Есть кто?", phone="998900000001", ago=0)
        from apps.notifications.models import WaMessage
        WaMessage.objects.filter(phone="998900000001").update(created_at=night - timedelta(minutes=1))
        n, calls = self._tick([_final("Здравствуйте! Чем помочь?")], now=night)
        self.assertEqual(n, 1)

    def test_admin_reply_or_pause_silences_bot(self):
        from apps.notifications.models import WaMessage
        from apps.notifications.patient_assistant import set_paused
        first = self._in("Сколько стоит чистка?", ago=10)
        out = WaMessage.objects.create(direction="out", channel="wa", phone=first.phone, body="200 000",
                                       sent_by=self.admin, clinic=self.clinic)
        WaMessage.objects.filter(pk=out.pk).update(created_at=self.noon - timedelta(minutes=5))
        n, calls = self._tick([])
        self.assertEqual((n, calls), (0, []))
        first.refresh_from_db()
        self.assertEqual(first.ai_status, "skip")
        m2 = self._in("Привет", phone="998901234567", ago=10)
        set_paused(self.clinic, "wa", "998901234567", True)
        n, calls = self._tick([])
        self.assertEqual((n, calls), (0, []))
        m2.refresh_from_db()
        self.assertEqual(m2.ai_status, "skip")

    def test_ai_led_chat_answers_without_delay_until_manager_joins(self):
        from apps.notifications.models import WaMessage
        from apps.notifications.patient_assistant import is_paused
        phone = "998907770000"
        self._in("Здравствуйте", phone=phone, ago=10)
        n, _ = self._tick([_final("Здравствуйте! Чем помочь?")])
        self.assertEqual(n, 1)
        # разговор ведёт ассистент — следующее сообщение без 5-минутной задержки
        self._in("Сколько стоит чистка?", phone=phone, ago=1)
        n, _ = self._tick([_final("200 000 сум.")])
        self.assertEqual(n, 1)
        # менеджер ответил из CRM — на это сообщение ассистент не отвечает
        out = WaMessage.objects.create(direction="out", channel="wa", phone=phone, body="Я подключусь",
                                       sent_by=self.admin, clinic=self.clinic)
        WaMessage.objects.filter(pk=out.pk).update(created_at=self.noon - timedelta(seconds=50))
        m = self._in("Спасибо", phone=phone, ago=0)
        WaMessage.objects.filter(pk=m.pk).update(created_at=self.noon - timedelta(seconds=30))
        n, calls = self._tick([])
        self.assertEqual((n, calls), (0, []))
        self.assertFalse(is_paused(self.clinic, "wa", phone, self.noon))
        # пациент пишет снова: менеджер ведёт чат — ассистент ждёт его 5 минут, а не отвечает сразу
        m2 = self._in("А когда можно прийти?", phone=phone, ago=0)
        WaMessage.objects.filter(pk=m2.pk).update(created_at=self.noon + timedelta(seconds=10))
        n, calls = self._tick([], now=self.noon + timedelta(minutes=1))
        self.assertEqual((n, calls), (0, []))
        # менеджер молчит 5 минут — отвечает ассистент
        n, _ = self._tick([_final("Можно завтра в 10:00.")], now=self.noon + timedelta(minutes=6))
        self.assertEqual(n, 1)

    def test_phone_reply_from_clinic_makes_assistant_wait_for_manager(self):
        from apps.notifications.patient_assistant import is_paused, manager_active, set_paused
        phone = "998907771111"
        m = self._in("Привет", phone=phone, ago=1)
        payload = {"typeWebhook": "outgoingMessageReceived", "instanceData": {"idInstance": 1},
                   "senderData": {"chatId": phone + "@c.us"}}
        with override_settings(GREENAPI_WEBHOOK_KEY="k"):
            Client().post("/notifications/wa-webhook/?key=k", json.dumps(payload),
                          content_type="application/json")
        m.refresh_from_db()
        self.assertEqual(m.ai_status, "skip")       # на то, на что ответил менеджер, ассистент не отвечает
        self.assertFalse(is_paused(self.clinic, "wa", phone))
        self.assertTrue(manager_active(self.clinic, "wa", phone))
        # выключенный вручную ассистент ответ менеджера не включает обратно
        set_paused(self.clinic, "wa", phone, True, reason="Выключил Админ")
        with override_settings(GREENAPI_WEBHOOK_KEY="k"):
            Client().post("/notifications/wa-webhook/?key=k", json.dumps(payload),
                          content_type="application/json")
        self.assertTrue(is_paused(self.clinic, "wa", phone))

    def test_known_phone_books_without_asking_name(self):
        from apps.appointments.models import Appointment
        # пациент есть в базе, но сообщение к нему не привязано
        self._in("Да, запишите", phone="998901112233", ago=10)
        start = "%sT16:00" % self.tomorrow.isoformat()
        n, calls = self._tick([
            _tool_call("book_appointment", {"doctor_id": self.doctor.pk, "start": start}),
            _final("Записал вас на 16:00."),
        ])
        self.assertEqual(n, 1)
        self.assertTrue(Appointment.objects.filter(patient=self.patient).exists())
        self.assertIn("Нилуфар", calls[0]["messages"][0]["content"])   # модель знает, кто пишет

    def test_wrong_doctor_id_falls_back_to_name(self):
        from apps.appointments.models import Appointment
        self._in("Да, запишите", phone="998901112233", patient=self.patient)
        start = "%sT10:00" % self.tomorrow.isoformat()
        n, calls = self._tick([
            _tool_call("book_appointment", {"doctor_id": 99999, "doctor_name": "Хожибек", "start": start}),
            _final("Записал."),
        ])
        self.assertEqual(Appointment.objects.get(patient=self.patient).doctor, self.doctor)
        self.assertIn("id=%s Хожибек" % self.doctor.pk, calls[0]["messages"][0]["content"])

    def test_prices_in_clinic_currency(self):
        self.cs.currency = "KGS"
        self.cs.phone = "+996 555 12 34 56"
        self.cs.save()
        self._in("Сколько стоит чистка?", phone="998901112233", patient=self.patient)
        n, calls = self._tick([_tool_call("search_services", {"query": "истка"}), _final("Чистка — 200 000 сом.")])
        self.assertIn("Валюта клиники: сом (KGS)", calls[0]["messages"][0]["content"])
        self.assertIn("оставь телефон администратора", calls[0]["messages"][0]["content"])
        self.assertIn("Телефон администратора: +996 555 12 34 56", calls[0]["messages"][0]["content"])
        self.assertIn("200 000 сом", calls[1]["messages"][-1]["content"])

    def test_unknown_number_gets_clinic(self):
        from apps.notifications.models import WaMessage
        from apps.notifications.patient_assistant import assign_orphans, clinic_for_unknown_number
        from apps.tenancy import unscoped
        other = Clinic.objects.create(name="Другая", slug="pa-other")
        ClinicSettings.objects.update_or_create(clinic=other, defaults={"name": "Другая"})
        with patch("apps.notifications.patient_assistant._shared_number", return_value=""):
            # сотрудник клиники пишет со своего номера
            self.doctor.phone = "+996 553 676 710"
            self.doctor.save()
            self.assertEqual(clinic_for_unknown_number("996553676710"), self.clinic)
            # клиника недавно писала на этот номер
            WaMessage.objects.create(direction="out", channel="wa", phone="996700111222", body="x", clinic=other)
            self.assertEqual(clinic_for_unknown_number("996700111222"), other)
            # совсем новый номер — единственная клиника на общих ключах с ассистентом
            self.assertEqual(clinic_for_unknown_number("996700999888"), self.clinic)
            # входящее без клиники подхватывается командой
            with unscoped():
                m = WaMessage.objects.create(direction="in", channel="wa", phone="996700999888", body="Салом")
            assign_orphans()
            with unscoped():
                m.refresh_from_db()
            self.assertEqual(m.clinic, self.clinic)
        # номер общего инстанса указан в настройках клиники — она владелец
        ClinicSettings.objects.filter(clinic=other).update(wa_phone="+996 555 000 111", ai_patient_bot=True)
        with patch("apps.notifications.patient_assistant._shared_number", return_value="996555000111"):
            self.assertEqual(clinic_for_unknown_number("996700999777"), other)

    def test_new_number_gets_patient_card_and_appears_in_messengers(self):
        from apps.appointments.models import Appointment
        from apps.patients.models import Patient
        from apps.users.views import _newui_messages_data
        payload = {"typeWebhook": "incomingMessageReceived", "instanceData": {"idInstance": 1},
                   "senderData": {"chatId": "996551514445@c.us", "senderName": "zoniminov"},
                   "messageData": {"typeMessage": "textMessage", "textMessageData": {"textMessage": "Салом"}}}
        with override_settings(GREENAPI_WEBHOOK_KEY="k"), \
                patch("apps.notifications.patient_assistant._shared_number", return_value=""):
            Client().post("/notifications/wa-webhook/?key=k", json.dumps(payload), content_type="application/json")
        p = Patient.objects.get(phone_norm="551514445")
        self.assertEqual((p.first_name, p.last_name, p.source.name), ("zoniminov", "", "WhatsApp"))
        self.assertIn(p.pk, [c["id"] for c in _newui_messages_data(self.clinic)["clients"]])
        # запись: ассистент сначала спрашивает имя, с именем — записывает и обновляет карточку
        from apps.notifications.models import WaMessage
        WaMessage.objects.filter(patient=p).update(created_at=self.noon - timedelta(minutes=10))
        start = "%sT10:00" % self.tomorrow.isoformat()
        n, calls = self._tick([
            _tool_call("book_appointment", {"doctor_id": self.doctor.pk, "start": start}),
            _tool_call("book_appointment", {"doctor_id": self.doctor.pk, "start": start,
                                            "full_name": "Иминов Зафар"}, "c2"),
            _final("Записал."),
        ])
        self.assertIn("имя в WhatsApp: zoniminov", calls[0]["messages"][0]["content"])
        self.assertIn("имя и фамилию", calls[1]["messages"][-1]["content"])
        p.refresh_from_db()
        self.assertEqual((p.last_name, p.first_name), ("Иминов", "Зафар"))
        self.assertTrue(Appointment.objects.filter(patient=p).exists())

    def test_telegram_without_phone_assistant_asks_phone_then_books(self):
        from apps.appointments.models import Appointment
        from apps.notifications.patient_assistant import ensure_tg_patient
        auto = ensure_tg_patient(self.clinic, 4242, {"first_name": "Зафар"})
        self._in("Хочу записаться на чистку завтра в 10", phone="4242", channel="tg", patient=auto)
        start = "%sT10:00" % self.tomorrow.isoformat()
        n, calls = self._tick([
            _tool_call("book_appointment", {"doctor_id": self.doctor.pk, "start": start, "full_name": "Иминов Зафар"}),
            _tool_call("book_appointment", {"doctor_id": self.doctor.pk, "start": start,
                                            "full_name": "Иминов Зафар", "phone": "+996 700 111 222"}, "c2"),
            _final("Записал."),
        ])
        self.assertEqual(n, 1)
        self.assertIn("номер не известен", calls[0]["messages"][0]["content"])
        self.assertIn("номер телефона", calls[1]["messages"][-1]["content"])
        auto.refresh_from_db()
        self.assertEqual((auto.last_name, auto.first_name, auto.phone), ("Иминов", "Зафар", "+996700111222"))
        self.assertTrue(Appointment.objects.filter(patient=auto).exists())
        self.assertEqual(self.sent[0][:2], ("tg", "4242"))

    def test_skipped_unlinked_telegram_message_is_picked_up(self):
        from apps.notifications.models import WaMessage
        from apps.notifications.patient_assistant import assign_orphans
        m = self._in("Тиш олиш нечи пул", phone="5551590", channel="tg")
        WaMessage.objects.filter(pk=m.pk).update(ai_status="skip", created_at=timezone.now() - timedelta(minutes=30))
        assign_orphans()
        m.refresh_from_db()
        self.assertEqual(m.ai_status, "")
        self.assertEqual(m.patient.telegram_chat_id, 5551590)

    def test_confirmation_hint_after_voice_yes(self):
        from apps.notifications.patient_assistant import _confirmation_hint
        ask = {"role": "assistant", "text": "Вы хотите запись к Одине на завтра в 09:15? Подтверждаете запись?"}
        for said in ("🎤 Да, подтверждаю", "Ха, майли", "Подтверждаю", "запишите", "ok"):
            self.assertTrue(_confirmation_hint([ask, {"role": "user", "text": said}]), said)
        self.assertIsNone(_confirmation_hint([ask, {"role": "user", "text": "Нет, лучше в 10"}]))
        # голосом повторил время: «на тогуз он беш» → распознано «На току за 15»
        self.assertTrue(_confirmation_hint([ask, {"role": "user", "text": "🎤 На току за 15"}]))
        self.assertTrue(_confirmation_hint([ask, {"role": "user", "text": "🎤 Ооба, макул"}]))
        self.assertIsNone(_confirmation_hint([ask, {"role": "user", "text": "Нет, не 15, давайте 16:30"}]))
        self.assertIsNone(_confirmation_hint([{"role": "assistant", "text": "Чем помочь?"},
                                              {"role": "user", "text": "Да"}]))
        # подсказка уходит модели последним системным сообщением
        self._in("Да", phone="998901112233", patient=self.patient, ago=10)
        from apps.notifications.models import WaMessage
        out = WaMessage.objects.create(direction="out", channel="wa", phone="998901112233", by_ai=True,
                                       body=ask["text"], clinic=self.clinic, patient=self.patient)
        WaMessage.objects.filter(pk=out.pk).update(created_at=self.noon - timedelta(minutes=11))
        n, calls = self._tick([_final("Записал.")])
        self.assertEqual(calls[0]["messages"][-1]["role"], "system")
        self.assertIn("ПОДТВЕРДИЛ", calls[0]["messages"][-1]["content"])

    def test_command_single_pass_logs_tool_calls(self):
        from io import StringIO
        from django.core.management import call_command
        from apps.notifications.models import WaMessage
        m = self._in("Привет", phone="998901112233")
        # команда берёт настоящее «сейчас»: сообщение пришло 10 минут назад (дольше задержки)
        WaMessage.objects.filter(pk=m.pk).update(created_at=timezone.now() - timedelta(minutes=10))
        buf = StringIO()
        with patch("apps.notifications.assistant._request",
                   side_effect=[(_tool_call("clinic_info", {}), None), (_final("Здравствуйте!"), None)]), \
                patch("apps.notifications.whatsapp.wa_send_text", return_value=True):
            call_command("patient_assistant_tick", "--loop", "0", stdout=buf)
        self.assertIn("clinic_info(", buf.getvalue())
        self.assertIn("ответ: Здравствуйте!", buf.getvalue())

    def test_replay_command_is_dry_run(self):
        from io import StringIO
        from django.core.management import call_command
        from apps.appointments.models import Appointment
        self._in("Да, запишите", phone="998901112233")
        start = "%sT10:00" % self.tomorrow.isoformat()
        buf = StringIO()
        with patch("apps.notifications.assistant._request", side_effect=[
                (_tool_call("book_appointment", {"doctor_id": self.doctor.pk, "start": start}), None),
                (_final("Записал."), None)]):
            call_command("patient_ai_replay", "--clinic", str(self.clinic.pk), "--phone", "2233", stdout=buf)
        self.assertIn('"dry_run": true', buf.getvalue())
        self.assertFalse(Appointment.objects.exists())

    def test_system_reminder_echo_does_not_pause_and_resume_answers(self):
        from apps.notifications.models import WaMessage
        from apps.notifications.patient_assistant import is_paused
        phone = "996553676710"
        self.patient.phone = "+" + phone
        self.patient.save()
        WaMessage.objects.create(direction="out", channel="wa", phone=phone, clinic=self.clinic,
                                 body="⏰ *SADAF*\n\nЗдравствуйте, *Нилуфар*! Напоминаем: ваш приём сегодня в 16:00")
        payload = {"typeWebhook": "outgoingMessageReceived", "instanceData": {"idInstance": 1},
                   "senderData": {"chatId": phone + "@c.us"},
                   "messageData": {"typeMessage": "extendedTextMessage", "extendedTextMessageData": {
                       "text": "⏰ *SADAF*\n\nЗдравствуйте, *Нилуфар*! Напоминаем: ваш приём сегодня в 16:00"}}}
        with override_settings(GREENAPI_WEBHOOK_KEY="k"):
            Client().post("/notifications/wa-webhook/?key=k", json.dumps(payload), content_type="application/json")
        self.assertFalse(is_paused(self.clinic, "wa", phone))
        # ассистента выключили, сообщение пропущено; включили — ответит
        c = Client()
        c.force_login(self.admin)
        c.post("/patients/%s/ai-bot/" % self.patient.pk, {"paused": "1"})
        m = self._in("Салом", phone=phone, patient=self.patient, ago=0)
        WaMessage.objects.filter(pk=m.pk).update(ai_status="skip", created_at=timezone.now() - timedelta(minutes=3))
        c.post("/patients/%s/ai-bot/" % self.patient.pk, {"paused": "0"})
        m.refresh_from_db()
        self.assertEqual(m.ai_status, "")

    def test_reschedule_and_cancel_only_own_appointments(self):
        from apps.appointments.models import Appointment
        from apps.patients.models import Patient
        other = Patient.objects.create(first_name="Чужой", last_name="Пациент", phone="+998905550000", clinic=self.clinic)
        st = timezone.make_aware(datetime.combine(self.tomorrow, time(10, 0)))
        mine = Appointment.objects.create(patient=self.patient, doctor=self.doctor, branch=self.branch,
                                          start_at=st, end_at=st + timedelta(hours=1), clinic=self.clinic)
        theirs = Appointment.objects.create(patient=other, doctor=self.doctor, branch=self.branch,
                                            start_at=st + timedelta(hours=3), end_at=st + timedelta(hours=4), clinic=self.clinic)
        self._in("Перенесите на 11:00", phone="998901112233", patient=self.patient)
        n, calls = self._tick([
            _tool_call("my_appointments", {}),
            _tool_call("reschedule_appointment", {"appointment_id": mine.pk,
                                                  "new_start": "%sT10:30" % self.tomorrow}, "c2"),
            _tool_call("cancel_appointment", {"appointment_id": theirs.pk}, "c3"),
            _final("Перенёс на 10:30."),
        ])
        my_list = json.loads(calls[1]["messages"][-1]["content"])
        self.assertEqual([x["id"] for x in my_list["appointments"]], [mine.pk])
        mine.refresh_from_db(); theirs.refresh_from_db()
        self.assertEqual(timezone.localtime(mine.start_at).strftime("%H:%M"), "10:30")
        self.assertEqual(theirs.status, "scheduled")      # чужую запись не тронул
        self.assertIn("не найдена", calls[3]["messages"][-1]["content"])

    def test_call_admin_pauses_chat(self):
        from apps.notifications.patient_assistant import is_paused
        self._in("Хочу пожаловаться", phone="998901112233", patient=self.patient)
        self._tick([_tool_call("call_admin", {"reason": "жалоба"}), _final("Передал администратору.")])
        self.assertTrue(is_paused(self.clinic, "wa", "998901112233"))

    def test_telegram_linked_patient_answered_unlinked_skipped(self):
        self._in("Когда мой приём?", phone="777", channel="tg", patient=self.patient)
        self._in("привет", phone="888", channel="tg")
        n, _ = self._tick([_final("У вас нет предстоящих записей.")])
        self.assertEqual(n, 1)
        self.assertEqual(self.sent[0][:2], ("tg", "777"))

    def test_disabled_clinic_does_nothing(self):
        self.cs.ai_patient_bot = False
        self.cs.save()
        self._in("Привет")
        n, calls = self._tick([])
        self.assertEqual((n, calls), (0, []))

    def test_settings_toggle_and_chat_pause_endpoint(self):
        c = Client()
        c.force_login(self.admin)
        self.cs.ai_patient_bot = False
        self.cs.save()
        c.post("/notifications/wa-settings/", {"ai_patient_present": "1", "ai_patient_bot": "on",
                                                "ai_patient_delay_min": "3", "wa_remind_debt_days": "0"})
        self.cs.refresh_from_db()
        self.assertTrue(self.cs.ai_patient_bot)
        self.assertEqual(self.cs.ai_patient_delay_min, 3)
        self.assertIsNotNone(self.cs.ai_patient_since)
        # старая форма рассылок без полей ассистента его не выключает
        c.post("/notifications/wa-settings/", {"wa_remind_debt_days": "0"})
        self.cs.refresh_from_db()
        self.assertTrue(self.cs.ai_patient_bot)
        self._in("привет", phone="998901112233", patient=self.patient)
        r = c.post("/patients/%s/ai-bot/" % self.patient.pk, {"paused": "1"})
        self.assertEqual(r.json(), {"on": True, "paused": True})
        msgs = c.get("/patients/%s/wa-messages/" % self.patient.pk).json()
        self.assertTrue(msgs["aiBot"]["paused"])
