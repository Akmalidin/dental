"""Treatment plans — multi-stage treatment with per-tooth tracking."""
from django.db import models
from django.conf import settings


class TreatmentPlan(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_APPROVED, "Согласован"),
        (STATUS_IN_PROGRESS, "В процессе"),
        (STATUS_COMPLETED, "Завершён"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="treatment_plans", verbose_name="Пациент"
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="treatment_plans", verbose_name="Врач"
    )
    title = models.CharField(max_length=300, verbose_name="Название плана")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, verbose_name="Статус")
    notes = models.TextField(blank=True, verbose_name="Примечания")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "План лечения"
        verbose_name_plural = "Планы лечения"
        ordering = ["-created_at"]

    def __str__(self):
        return f"План #{self.pk} — {self.patient}"

    @property
    def total_price(self):
        from django.db.models import Sum
        from decimal import Decimal
        return self.items.aggregate(s=Sum("price"))["s"] or Decimal(0)

    @property
    def done_price(self):
        from django.db.models import Sum
        from decimal import Decimal
        return self.items.filter(status="done").aggregate(s=Sum("price"))["s"] or Decimal(0)

    @property
    def completion_pct(self):
        total = self.items.count()
        if not total:
            return 0
        done = self.items.filter(status="done").count()
        return int(done / total * 100)


class TreatmentPlanStage(models.Model):
    """A stage (этап) within a treatment plan, grouping several services."""

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.CASCADE, related_name="stages")
    title = models.CharField(max_length=200, blank=True, verbose_name="Название этапа")
    duration_min = models.PositiveIntegerField(null=True, blank=True, verbose_name="Продолжительность (мин)")
    visit = models.ForeignKey(
        "treatments.Treatment", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="plan_stages", verbose_name="Визит",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Этап плана"
        verbose_name_plural = "Этапы плана"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title or f"Этап #{self.pk}"

    @property
    def total(self):
        from decimal import Decimal
        return sum((it.subtotal for it in self.items.all()), Decimal(0))


class TreatmentPlanItem(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SCHEDULED = "scheduled"
    STATUS_DONE = "done"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Ожидает"),
        (STATUS_SCHEDULED, "Запланирован"),
        (STATUS_DONE, "Выполнен"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(
        "services.Service", on_delete=models.PROTECT, related_name="plan_items", verbose_name="Услуга"
    )
    stage = models.ForeignKey(
        "treatments.TreatmentPlanStage", on_delete=models.CASCADE, null=True, blank=True,
        related_name="items", verbose_name="Этап",
    )
    tooth_number = models.CharField(max_length=120, blank=True, verbose_name="Зуб(ы)")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Цена")
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Скидка %")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Количество")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="plan_items", verbose_name="Врач"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, verbose_name="Статус")
    sort_order = models.PositiveIntegerField(default=0)
    treatment = models.ForeignKey(
        "treatments.Treatment", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="plan_items", verbose_name="Выполнен в приёме"
    )

    class Meta:
        verbose_name = "Пункт плана"
        verbose_name_plural = "Пункты плана"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.service.name} — {self.price} сом"

    @property
    def subtotal(self):
        from decimal import Decimal
        gross = self.price * self.quantity
        return gross - (gross * self.discount / Decimal(100))
