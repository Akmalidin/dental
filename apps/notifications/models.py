from django.db import models
from django.conf import settings


class Notification(models.Model):
    TYPE_CHOICES = [
        ("appointment", "Запись"),
        ("task", "Задача"),
        ("payment", "Платёж"),
        ("system", "Система"),
        ("reminder", "Напоминание"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Пользователь",
    )
    clinic = models.ForeignKey(
        "users.Clinic", on_delete=models.CASCADE, null=True, blank=True,
        related_name="+", verbose_name="Клиника", db_index=True,
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Тип")
    title = models.CharField(max_length=300, verbose_name="Заголовок")
    body = models.TextField(blank=True, verbose_name="Сообщение")
    is_read = models.BooleanField(default=False)
    link = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.title}"

    @classmethod
    def send(cls, user, title, body="", type="system", link=""):
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic() or getattr(user, "clinic", None)
        n = cls.objects.create(user=user, clinic=clinic, title=title, body=body, type=type, link=link)
        # дополнительно — web push (телефон/фон, даже если вкладка закрыта)
        try:
            from .push import send_web_push
            send_web_push(user, title, body, link or "/")
        except Exception:
            pass
        return n


class PushSubscription(models.Model):
    """Подписка устройства на web push (Service Worker)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Push-подписка"
        verbose_name_plural = "Push-подписки"

    def __str__(self):
        return f"{self.user} · {self.endpoint[:40]}"
