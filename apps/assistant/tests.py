import datetime

from django.test import TestCase
from django.utils import timezone

from apps.assistant.models import Conversation
from apps.tenancy import set_current_clinic, clear_current_clinic
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
