import datetime

from django.test import TestCase
from django.utils import timezone

from apps.assistant.models import Conversation
from apps.tenancy import set_current_clinic, clear_current_clinic
from apps.users.models import Clinic, User


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
