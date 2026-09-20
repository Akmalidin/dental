import datetime
import datetime as dt
from decimal import Decimal

import json
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.assistant.models import Conversation
from apps.tenancy import set_current_clinic, clear_current_clinic
from apps.appointments.models import Appointment
from apps.assistant.tools import openai_schemas, run_tool
from apps.patients.models import Patient
from apps.users.models import Branch, Clinic, User


class ConversationMemoryTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника П", slug="clinic-memory")
        set_current_clinic(self.clinic)
        self.user = User.objects.create(login="memo", name="Мемо", clinic=self.clinic)

    def tearDown(self):
        clear_current_clinic()

    def test_active_for_creates_one_conversation(self):
        first = Conversation.active_for(self.user)
        second = Conversation.active_for(self.user)
        self.assertEqual(first.pk, second.pk)

    def test_stale_conversation_is_replaced(self):
        old = Conversation.active_for(self.user)
        old.add("user", "давний вопрос")
        Conversation.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - datetime.timedelta(hours=13)
        )
        fresh = Conversation.active_for(self.user)
        self.assertNotEqual(old.pk, fresh.pk)

    def test_recent_returns_chronological_tail(self):
        conv = Conversation.active_for(self.user)
        for i in range(15):
            conv.add("user", "вопрос %d" % i)
        recent = conv.recent(limit=12)
        self.assertEqual(len(recent), 12)
        self.assertEqual(recent[0].text, "вопрос 3")
        self.assertEqual(recent[-1].text, "вопрос 14")

    def test_add_records_tool_call(self):
        conv = Conversation.active_for(self.user)
        msg = conv.add("assistant", "нашёл 3", tool_name="find_patient",
                       tool_args={"query": "Иван"}, rows_count=3)
        self.assertEqual(msg.tool_name, "find_patient")
        self.assertEqual(msg.tool_args["query"], "Иван")
        self.assertEqual(msg.rows_count, 3)

    def test_add_advances_updated_at_with_mismatched_current_clinic(self):
        """Регрессия: updated_at должен продвигаться, даже если thread-local
        текущая клиника не совпадает с клиникой беседы (например, фоновый
        воркер обработал одну клинику и не сбросил контекст перед тем, как
        тронуть данные другой).

        ВАЖНО: сценарий "текущей клиники вообще нет" (clear_current_clinic())
        здесь не воспроизводит баг — проверено эмпирически. В
        apps.tenancy._apply_clinic() фильтр по клинике применяется, только
        когда get_current_clinic() возвращает не-None; при None фильтр не
        накладывается вовсе (что логично: не о чем фильтровать), так что даже
        старая реализация через
        Conversation.objects.filter(pk=...).update(...) находила строку без
        текущей клиники. Баг проявляется именно при НЕСОВПАДЕНИИ текущей
        клиники с клиникой записи (ClinicManager фильтрует по чужой clinic и
        update() бьёт мимо pk).

        Прежняя реализация обновляла updated_at через
        Conversation.objects.filter(...).update(), то есть через
        ClinicManager с фильтром по текущей клинике — в описанном сценарии
        update() не находил строку и молча не делал ничего, беседа
        «протухала» раньше срока.
        """
        conv = Conversation.active_for(self.user)
        old_time = timezone.now() - datetime.timedelta(minutes=5)
        Conversation.objects.filter(pk=conv.pk).update(updated_at=old_time)
        conv.refresh_from_db(fields=["updated_at"])

        other_clinic = Clinic.objects.create(name="Другая клиника", slug="clinic-other")
        set_current_clinic(other_clinic)   # имитируем «чужой» контекст потока
        try:
            conv.add("user", "привет")
        finally:
            set_current_clinic(self.clinic)

        conv.refresh_from_db(fields=["updated_at"])
        self.assertGreater(conv.updated_at, old_time)

    def test_active_for_does_not_duplicate_existing_active_conversation(self):
        """Базовая проверка: повторные вызовы не плодят лишних бесед.

        ВНИМАНИЕ: гонку (два параллельных запроса одновременно проходят
        active_for() и оба не видят чужую ещё не закоммиченную запись) этот
        тест НЕ покрывает — три последовательных вызова в одном потоке
        пройдут при любой реализации, даже без select_for_update(). Честно
        воспроизвести гонку юнит-тестом на SQLite нельзя: select_for_update()
        здесь не блокирует, а тест на реальных потоках был бы флаки.
        Защита от гонки — select_for_update() в active_for() — работает и
        проверяема только на бэкенде с реальными блокировками (в проде —
        PostgreSQL, см. config/settings/server.py).
        """
        Conversation.active_for(self.user)
        Conversation.active_for(self.user)
        Conversation.active_for(self.user)
        self.assertEqual(Conversation.objects.filter(user=self.user).count(), 1)


class ToolClinicIsolationTestCase(TestCase):
    """Главный тест безопасности: инструмент, вызванный сотрудником одной
    клиники, не должен возвращать ничего из другой — даже если пациенты
    названы одинаково."""

    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника А", slug="tool-clinic-a")
        self.clinic_b = Clinic.objects.create(name="Клиника Б", slug="tool-clinic-b")
        self.branch_a = Branch.objects.create(
            name="А", address="-", phone="0", is_main=True, clinic=self.clinic_a)
        self.branch_b = Branch.objects.create(
            name="Б", address="-", phone="0", is_main=True, clinic=self.clinic_b)
        self.user_a = User.objects.create(login="tool-a", name="А", clinic=self.clinic_a)
        set_current_clinic(self.clinic_a)
        Patient.objects.create(first_name="Иван", last_name="Тестов", phone="111",
                               branch=self.branch_a, clinic=self.clinic_a)
        set_current_clinic(self.clinic_b)
        Patient.objects.create(first_name="Иван", last_name="Тестов", phone="222",
                               branch=self.branch_b, clinic=self.clinic_b)

    def tearDown(self):
        clear_current_clinic()

    def test_find_patient_returns_only_own_clinic(self):
        set_current_clinic(self.clinic_a)
        rows, error = run_tool("find_patient", self.user_a, {"query": "Иван"})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phone"], "111")

    def test_find_patient_by_phone(self):
        set_current_clinic(self.clinic_a)
        rows, error = run_tool("find_patient", self.user_a, {"query": "111"})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)

    def test_unknown_tool_returns_error(self):
        set_current_clinic(self.clinic_a)
        rows, error = run_tool("drop_everything", self.user_a, {})
        self.assertEqual(rows, [])
        self.assertIsNotNone(error)

    def test_schemas_are_wellformed(self):
        schemas = openai_schemas()
        self.assertTrue(schemas)
        for s in schemas:
            self.assertEqual(s["type"], "function")
            self.assertIn("name", s["function"])
            self.assertIn("parameters", s["function"])


class AssistantToolsTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника И", slug="tools-clinic")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(
            name="Главный", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.doctor = User.objects.create(login="doc-tools", name="Доктор", clinic=self.clinic)
        self.user = User.objects.create(login="adm-tools", name="Админ", clinic=self.clinic)
        self.patient = Patient.objects.create(
            first_name="Пётр", last_name="Должников", phone="777",
            branch=self.branch, clinic=self.clinic)
        self.today = timezone.localdate()
        start = timezone.make_aware(dt.datetime.combine(self.today, dt.time(10, 0)))
        Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch,
            start_at=start, end_at=start + dt.timedelta(minutes=30),
            status=Appointment.STATUS_SCHEDULED, clinic=self.clinic)

    def tearDown(self):
        clear_current_clinic()

    def test_appointments_on_date(self):
        rows, error = run_tool("appointments_on_date", self.user,
                               {"date": self.today.isoformat()})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["patient"], self.patient.full_name)
        self.assertEqual(rows[0]["time"], "10:00")

    def test_appointments_on_bad_date_returns_error(self):
        rows, error = run_tool("appointments_on_date", self.user, {"date": "31.02.2026"})
        self.assertEqual(rows, [])
        self.assertIsNotNone(error)

    def test_patients_with_debt(self):
        Patient.all_objects.filter(pk=self.patient.pk).update(balance=Decimal("-500"))
        rows, error = run_tool("patients_with_debt", self.user, {})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["debt"], 500.0)

    def test_doctor_workload_counts_appointments(self):
        rows, error = run_tool("doctor_workload", self.user,
                               {"date_from": self.today.isoformat(),
                                "date_to": self.today.isoformat()})
        self.assertIsNone(error)
        by_doctor = {r["doctor"]: r["appointments"] for r in rows}
        self.assertEqual(by_doctor.get("Доктор"), 1)

    def test_revenue_for_period_empty(self):
        rows, error = run_tool("revenue_for_period", self.user,
                               {"date_from": self.today.isoformat(),
                                "date_to": self.today.isoformat()})
        self.assertIsNone(error)
        self.assertEqual(rows[0]["total"], 0.0)


class AllToolsClinicIsolationTestCase(TestCase):
    """Изоляция для ОСТАЛЬНЫХ инструментов, не только find_patient.

    В брифе тест на изоляцию был один, на поиск пациента. Но утечь может
    любой инструмент: достаточно где-то написать .all_objects вместо
    .objects. Здесь в двух клиниках заведены одинаковые данные, и каждый
    инструмент обязан вернуть только своё.
    """

    def setUp(self):
        self.a = Clinic.objects.create(name="А", slug="iso-all-a")
        self.b = Clinic.objects.create(name="Б", slug="iso-all-b")
        self.today = timezone.localdate()
        self.user_a = User.objects.create(login="iso-a", name="А", clinic=self.a)
        for clinic, tag, debt in ((self.a, "A", "-100"), (self.b, "B", "-900")):
            set_current_clinic(clinic)
            branch = Branch.objects.create(
                name="Ф" + tag, address="-", phone="0", is_main=True, clinic=clinic)
            doctor = User.objects.create(
                login="doc-iso-" + tag, name="Врач" + tag, clinic=clinic)
            patient = Patient.objects.create(
                first_name="Имя", last_name="Фам" + tag, phone="55" + tag,
                branch=branch, clinic=clinic)
            Patient.all_objects.filter(pk=patient.pk).update(balance=Decimal(debt))
            start = timezone.make_aware(dt.datetime.combine(self.today, dt.time(9, 0)))
            Appointment.objects.create(
                patient=patient, doctor=doctor, branch=branch,
                start_at=start, end_at=start + dt.timedelta(minutes=30),
                status=Appointment.STATUS_SCHEDULED, clinic=clinic)

    def tearDown(self):
        clear_current_clinic()

    def test_appointments_on_date_scoped(self):
        set_current_clinic(self.a)
        rows, error = run_tool("appointments_on_date", self.user_a,
                               {"date": self.today.isoformat()})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["doctor"], "ВрачA")

    def test_patients_with_debt_scoped(self):
        set_current_clinic(self.a)
        rows, error = run_tool("patients_with_debt", self.user_a, {})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["debt"], 100.0)

    def test_doctor_workload_scoped(self):
        set_current_clinic(self.a)
        rows, error = run_tool("doctor_workload", self.user_a,
                               {"date_from": self.today.isoformat(),
                                "date_to": self.today.isoformat()})
        self.assertIsNone(error)
        self.assertEqual([r["doctor"] for r in rows], ["ВрачA"])


class ProviderTestCase(TestCase):
    """HTTP наружу не ходим: подменяем _post_openai — единственное место,
    где провайдер обращается в сеть."""

    @override_settings(OPENAI_API_KEY="")
    def test_not_available_without_key(self):
        from apps.assistant import provider
        self.assertFalse(provider.openai_available())

    @override_settings(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-4o-mini")
    def test_text_answer_parsed(self):
        from apps.assistant import provider
        payload = {"choices": [{"message": {"content": "Готово"}}]}
        with mock.patch.object(provider, "_post_openai", return_value=(payload, None)):
            result, error = provider.complete([{"role": "user", "content": "привет"}])
        self.assertIsNone(error)
        self.assertEqual(result["kind"], "text")
        self.assertEqual(result["text"], "Готово")

    @override_settings(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-4o-mini")
    def test_tool_call_parsed(self):
        from apps.assistant import provider
        payload = {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "find_patient",
                          "arguments": json.dumps({"query": "Иван"})}}
        ]}}]}
        with mock.patch.object(provider, "_post_openai", return_value=(payload, None)):
            result, error = provider.complete([{"role": "user", "content": "найди Ивана"}])
        self.assertIsNone(error)
        self.assertEqual(result["kind"], "tool")
        self.assertEqual(result["name"], "find_patient")
        self.assertEqual(result["args"]["query"], "Иван")

    @override_settings(OPENAI_API_KEY="k")
    def test_broken_tool_arguments_reported(self):
        from apps.assistant import provider
        payload = {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "find_patient", "arguments": "{не json"}}
        ]}}]}
        with mock.patch.object(provider, "_post_openai", return_value=(payload, None)):
            result, error = provider.complete([{"role": "user", "content": "x"}])
        self.assertIsNone(result)
        self.assertIsNotNone(error)

    @override_settings(OPENAI_API_KEY="k")
    def test_http_error_propagated(self):
        from apps.assistant import provider
        with mock.patch.object(provider, "_post_openai", return_value=(None, "таймаут")):
            result, error = provider.complete([{"role": "user", "content": "x"}])
        self.assertIsNone(result)
        self.assertEqual(error, "таймаут")

    @override_settings(OPENAI_API_KEY="k")
    def test_unexpected_payload_reported(self):
        """Ответ без choices не должен ронять ассистента исключением."""
        from apps.assistant import provider
        with mock.patch.object(provider, "_post_openai", return_value=({}, None)):
            result, error = provider.complete([{"role": "user", "content": "x"}])
        self.assertIsNone(result)
        self.assertIsNotNone(error)

    @override_settings(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-4o-mini")
    def test_tools_are_sent_in_request(self):
        """Инструменты должны реально уходить в тело запроса.

        Без этого модель никогда не попросит инструмент, и ассистент молча
        выродится в обычный чат без доступа к данным — снаружи это выглядит
        не как поломка, а как «ИИ почему-то не знает наших пациентов».
        """
        from apps.assistant import provider
        from apps.assistant.tools import openai_schemas

        captured = {}

        def fake_post(body):
            captured.update(body)
            return {"choices": [{"message": {"content": "ок"}}]}, None

        with mock.patch.object(provider, "_post_openai", side_effect=fake_post):
            provider.complete([{"role": "user", "content": "x"}], tools=openai_schemas())

        self.assertIn("tools", captured)
        self.assertEqual(captured["tool_choice"], "auto")
        names = {t["function"]["name"] for t in captured["tools"]}
        self.assertIn("find_patient", names)
        self.assertIn("appointments_on_date", names)
        self.assertEqual(captured["model"], "gpt-4o-mini")

    @override_settings(OPENAI_API_KEY="k")
    def test_tools_omitted_when_not_given(self):
        """Без инструментов поля tools в запросе быть не должно — иначе
        OpenAI отвергнет запрос с пустым списком."""
        from apps.assistant import provider

        captured = {}

        def fake_post(body):
            captured.update(body)
            return {"choices": [{"message": {"content": "ок"}}]}, None

        with mock.patch.object(provider, "_post_openai", side_effect=fake_post):
            provider.complete([{"role": "user", "content": "x"}])

        self.assertNotIn("tools", captured)
        self.assertNotIn("tool_choice", captured)
