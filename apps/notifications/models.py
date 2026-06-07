from django.db import models
from django.conf import settings
from apps.tenancy import ClinicScopedModel


class MessageTemplate(ClinicScopedModel):
    """Редактируемый шаблон WhatsApp-сообщения. Плейсхолдеры:
    {имя} {фамилия} {фио} {телефон} {клиника} {долг} {баланс} {дата} {время} {врач} {сумма}"""
    KIND_CHOICES = [
        ("manual", "Произвольное"),
        ("appointment", "О записи"),
        ("reminder", "Напоминание о приёме"),
        ("confirm", "Подтверждение записи"),
        ("debt", "О задолженности"),
        ("birthday", "Поздравление"),
    ]
    name = models.CharField(max_length=200, verbose_name="Название")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="manual", verbose_name="Тип")
    body = models.TextField(verbose_name="Текст сообщения")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Шаблон сообщения"
        verbose_name_plural = "Шаблоны сообщений"
        ordering = ["kind", "name"]

    def __str__(self):
        return self.name


class WaMessage(ClinicScopedModel):
    """История WhatsApp-переписки с пациентом (лог исходящих + входящие для чата)."""
    DIR_OUT, DIR_IN = "out", "in"
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="wa_messages",
        null=True, blank=True, verbose_name="Пациент",
    )
    direction = models.CharField(max_length=3, choices=[(DIR_OUT, "Исходящее"), (DIR_IN, "Входящее")],
                                 default=DIR_OUT)
    phone = models.CharField(max_length=30, blank=True)
    body = models.TextField()
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="+")
    ok = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "WhatsApp-сообщение"
        verbose_name_plural = "WhatsApp-сообщения"
        ordering = ["created_at"]


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
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Отправитель",
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
    def send(cls, user, title, body="", type="system", link="", actor=None):
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic() or getattr(user, "clinic", None)
        n = cls.objects.create(user=user, clinic=clinic, actor=actor,
                               title=title, body=body, type=type, link=link)
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
