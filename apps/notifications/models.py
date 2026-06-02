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
        return cls.objects.create(user=user, title=title, body=body, type=type, link=link)
