import datetime

from django.db import models
from django.utils import timezone

from apps.tenancy import ClinicScopedModel

# Через сколько без новых реплик разговор считается завершённым. 12 часов —
# это «в пределах смены»: вернувшись после обеда, сотрудник продолжает тот
# же разговор, а на следующее утро начинает с чистого листа, и история не
# превращается в одну бесконечную ленту.
STALE_AFTER = datetime.timedelta(hours=12)


class Conversation(ClinicScopedModel):
    """Беседа сотрудника с ассистентом. Одна активная на пользователя."""

    user = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, related_name="assistant_conversations",
        verbose_name="Сотрудник",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="Закрыта")

    class Meta:
        verbose_name = "Беседа с ассистентом"
        verbose_name_plural = "Беседы с ассистентом"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self):
        return "Беседа %s от %s" % (self.user_id, self.created_at)

    @classmethod
    def active_for(cls, user):
        """Текущая беседа сотрудника. Создаёт новую, если прошлая устарела
        или была закрыта кнопкой «Очистить»."""
        conv = (cls.objects.filter(user=user, closed_at__isnull=True)
                .order_by("-updated_at").first())
        if conv is not None and timezone.now() - conv.updated_at < STALE_AFTER:
            return conv
        return cls.objects.create(user=user)

    def add(self, role, text, tool_name="", tool_args=None, rows_count=None):
        msg = Message.objects.create(
            conversation=self, role=role, text=text,
            tool_name=tool_name, tool_args=tool_args or {}, rows_count=rows_count,
        )
        # updated_at двигаем явно: auto_now срабатывает на save() самой
        # беседы, а пишем мы в дочернюю таблицу.
        Conversation.objects.filter(pk=self.pk).update(updated_at=timezone.now())
        self.refresh_from_db(fields=["updated_at"])
        return msg

    def recent(self, limit=12):
        """Последние реплики в хронологическом порядке — как их ждёт модель."""
        tail = list(self.messages.order_by("-created_at", "-pk")[:limit])
        return list(reversed(tail))


class Message(models.Model):
    """Реплика беседы. Поля tool_* это журнал: видно, какой инструмент
    отработал и сколько строк ушло во внешнюю модель."""

    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [(ROLE_USER, "Сотрудник"), (ROLE_ASSISTANT, "Ассистент")]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    text = models.TextField(blank=True)
    tool_name = models.CharField(max_length=64, blank=True, verbose_name="Инструмент")
    tool_args = models.JSONField(default=dict, blank=True, verbose_name="Параметры")
    rows_count = models.IntegerField(null=True, blank=True, verbose_name="Строк возвращено")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Реплика"
        verbose_name_plural = "Реплики"
        ordering = ["created_at", "pk"]

    def __str__(self):
        return "%s: %s" % (self.role, self.text[:50])
