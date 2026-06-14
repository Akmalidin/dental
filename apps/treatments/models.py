from decimal import Decimal
from django.db import models
from .models_plan import TreatmentPlan, TreatmentPlanItem  # noqa: F401
from .models_emr import MedicalRecordTemplate, MedicalRecord  # noqa: F401
from .models_teeth import ToothStatus, ToothCondition, DEFAULT_TOOTH_STATUSES  # noqa: F401
from django.conf import settings
from simple_history.models import HistoricalRecords
from apps.users.models import Branch
from apps.patients.models import Patient
from apps.services.models import Service
from apps.tenancy import ClinicSoftDeleteModel


class Treatment(ClinicSoftDeleteModel):
    STATUS_PLANNED = "planned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_PAID = "paid"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Запланирован"),
        (STATUS_IN_PROGRESS, "В процессе"),
        (STATUS_COMPLETED, "Завершён"),
        (STATUS_CANCELLED, "Отменён"),
        (STATUS_PAID, "Оплачен"),
    ]

    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="treatments", verbose_name="Пациент"
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="treatments",
        verbose_name="Врач",
    )
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="treatments", verbose_name="Филиал")
    appointment = models.ForeignKey(
        "appointments.Appointment", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="treatments", verbose_name="Запись",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED, verbose_name="Статус")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Сумма (сом)")
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Скидка")
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Оплачено")
    notes = models.TextField(blank=True, verbose_name="Заметки")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Приём"
        verbose_name_plural = "Приёмы"
        ordering = ["-created_at"]
        base_manager_name = "all_objects"

    def __str__(self):
        return f"Приём #{self.pk} — {self.patient}"

    @property
    def is_cancelled(self):
        return self.status == self.STATUS_CANCELLED

    @property
    def display_total(self):
        """Сумма для отображения: отменённый приём = 0."""
        return Decimal(0) if self.is_cancelled else self.total_amount

    @property
    def debt(self):
        if self.is_cancelled:
            return Decimal(0)
        return max(Decimal(0), self.total_amount - self.discount - self.paid_amount)

    @property
    def final_amount(self):
        if self.is_cancelled:
            return Decimal(0)
        return max(Decimal(0), self.total_amount - self.discount)

    def recalculate_total(self):
        total = sum(cure.price * cure.quantity for cure in self.cures.all())
        self.total_amount = total
        self.save(update_fields=["total_amount", "updated_at"])
        # сумма приёма изменилась → пересчитать баланс пациента
        if self.patient_id:
            self.patient.recalc_balance()


class TreatmentCure(models.Model):
    """A single procedure item within a treatment."""

    treatment = models.ForeignKey(Treatment, on_delete=models.CASCADE, related_name="cures")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="cures", verbose_name="Услуга")
    tooth_number = models.CharField(max_length=120, blank=True, verbose_name="Номер зуба")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Количество")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Цена")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cures",
        verbose_name="Врач",
    )
    technician = models.ForeignKey(
        "technicians.Technician",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cures",
        verbose_name="Техник",
    )

    class Meta:
        verbose_name = "Процедура приёма"
        verbose_name_plural = "Процедуры приёма"

    def __str__(self):
        return f"{self.service} × {self.quantity}"

    @property
    def subtotal(self):
        return self.price * self.quantity


class TreatmentFile(models.Model):
    """X-rays, documents, and other files attached to a treatment."""

    KIND_CHOICES = [
        ("xray", "Рентген"),
        ("before", "Фото «до»"),
        ("after", "Фото «после»"),
        ("document", "Документ"),
        ("other", "Другое"),
    ]

    treatment = models.ForeignKey(Treatment, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="treatments/%Y/%m/")
    tooth_number = models.IntegerField(null=True, blank=True, verbose_name="Зуб (FDI)")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="xray", verbose_name="Тип")
    name = models.CharField(max_length=200, verbose_name="Название")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="Загрузил"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Файл приёма"
        verbose_name_plural = "Файлы приёма"

    def __str__(self):
        return self.name

    @property
    def is_image(self):
        name = (self.file.name or "").lower()
        return name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))


class TreatmentFollowUp(models.Model):
    """Scheduled follow-up visit or reminder."""

    STATUS_CHOICES = [
        ("pending", "Ожидает"),
        ("completed", "Выполнен"),
        ("cancelled", "Отменён"),
    ]

    treatment = models.ForeignKey(Treatment, on_delete=models.CASCADE, related_name="followups")
    scheduled_at = models.DateTimeField(verbose_name="Дата повторного приёма")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Повторный приём"
        verbose_name_plural = "Повторные приёмы"
        ordering = ["scheduled_at"]

    def __str__(self):
        return f"Follow-up #{self.pk} — {self.scheduled_at:%d.%m.%Y}"
