from django.db import models
from django.conf import settings
from apps.users.models import Branch
from apps.patients.models import Patient
from apps.services.models import Service
from apps.tenancy import ClinicSoftDeleteModel


class CancellationReason(models.Model):
    """Reusable reasons for cancelling an appointment (managed in settings)."""

    name = models.CharField(max_length=200, verbose_name="Причина отмены")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Причина отмены"
        verbose_name_plural = "Причины отмены"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Cabinet(models.Model):
    """Treatment room / chair."""

    name = models.CharField(max_length=100, verbose_name="Кабинет")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="cabinets")
    color = models.CharField(max_length=7, default="#10B981", verbose_name="Цвет")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Кабинет"
        verbose_name_plural = "Кабинеты"
        ordering = ["branch", "name"]

    def __str__(self):
        return f"{self.branch} — {self.name}"


class Appointment(ClinicSoftDeleteModel):
    STATUS_SCHEDULED = "scheduled"
    STATUS_CONFIRMED = "confirmed"
    STATUS_ARRIVED = "arrived"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_NO_SHOW = "no_show"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Записан"),
        (STATUS_CONFIRMED, "Подтверждён"),
        (STATUS_ARRIVED, "Пришёл"),
        (STATUS_IN_PROGRESS, "Принимается"),
        (STATUS_COMPLETED, "Завершён"),
        (STATUS_NO_SHOW, "Не пришёл"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    SOURCE_CHOICES = [
        ("manual", "Вручную"),
        ("online", "Онлайн"),
        ("telegram", "Telegram"),
    ]

    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="Пациент",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name="Врач",
    )
    cabinet = models.ForeignKey(
        Cabinet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="Кабинет",
    )
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="appointments", verbose_name="Филиал")
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="Услуга (основная)",
    )
    services = models.ManyToManyField(
        Service, blank=True, related_name="appointments_multi", verbose_name="Услуги",
    )
    start_at = models.DateTimeField(verbose_name="Начало")
    end_at = models.DateTimeField(verbose_name="Конец")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED, verbose_name="Статус")
    cancellation_reason = models.ForeignKey(
        "appointments.CancellationReason", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="appointments", verbose_name="Причина отмены",
    )
    cancel_note = models.CharField(max_length=300, blank=True, verbose_name="Комментарий к отмене")
    notes = models.TextField(blank=True, verbose_name="Заметки")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="manual", verbose_name="Источник")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_appointments",
    )

    class Meta:
        verbose_name = "Запись"
        verbose_name_plural = "Записи"
        ordering = ["start_at"]
        base_manager_name = "all_objects"

    def __str__(self):
        patient_name = self.patient.full_name if self.patient else "—"
        return f"{patient_name} → {self.doctor} [{self.start_at:%d.%m %H:%M}]"

    @property
    def duration_minutes(self):
        delta = self.end_at - self.start_at
        return int(delta.total_seconds() / 60)
