import uuid
from django.db import models
from django.conf import settings
from apps.users.models import Branch
from apps.patients.models import Patient
from apps.tenancy import ClinicScopedModel


class ExpenseCategory(ClinicScopedModel):
    name = models.CharField(max_length=150, verbose_name="Категория расхода")

    class Meta:
        verbose_name = "Категория расхода"
        verbose_name_plural = "Категории расходов"

    def __str__(self):
        return self.name


class Payment(ClinicScopedModel):
    METHOD_CASH = "cash"
    METHOD_CARD = "card"
    METHOD_TRANSFER = "transfer"
    METHOD_ONLINE = "online"

    METHOD_CHOICES = [
        (METHOD_CASH, "Наличные"),
        (METHOD_CARD, "Карта"),
        (METHOD_TRANSFER, "Перевод"),
        (METHOD_ONLINE, "Онлайн"),
    ]

    TYPE_INCOME = "income"
    TYPE_REFUND = "refund"

    TYPE_CHOICES = [
        (TYPE_INCOME, "Оплата"),
        (TYPE_REFUND, "Возврат"),
    ]

    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="payments", verbose_name="Пациент"
    )
    treatment = models.ForeignKey(
        "treatments.Treatment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
        verbose_name="Приём",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Сумма")
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_CASH, verbose_name="Метод оплаты")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_INCOME, verbose_name="Тип")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="payments", verbose_name="Филиал")
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_payments", verbose_name="Принял"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    # Публичный токен для QR-чека (открывается без логина при сканировании).
    public_token = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    # True — оплата принята в кассе (администратором). False — принял врач напрямую.
    via_cashier = models.BooleanField(default=False, db_index=True, verbose_name="Принято в кассе")

    class Meta:
        verbose_name = "Платёж"
        verbose_name_plural = "Платежи"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.patient} — {self.amount} сом [{self.created_at:%d.%m.%Y}]"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._update_patient_balance()
        if self.treatment:
            self._update_treatment_paid()

    def delete(self, *args, **kwargs):
        # Запоминаем связанные объекты до удаления, затем пересчитываем баланс/оплату.
        patient = self.patient
        treatment_id = self.treatment_id
        super().delete(*args, **kwargs)
        if patient is not None:
            patient.recalc_balance()
        if treatment_id:
            from django.db.models import Sum
            from decimal import Decimal
            from apps.treatments.models import Treatment
            t = Treatment.all_objects.filter(pk=treatment_id).first()
            if t is not None:
                paid = t.payments.filter(type=self.TYPE_INCOME).aggregate(s=Sum("amount"))["s"] or Decimal(0)
                refund = t.payments.filter(type=self.TYPE_REFUND).aggregate(s=Sum("amount"))["s"] or Decimal(0)
                Treatment.objects.filter(pk=treatment_id).update(paid_amount=paid - refund)

    def _update_patient_balance(self):
        if self.patient_id:
            self.patient.recalc_balance()

    def _update_treatment_paid(self):
        from django.db.models import Sum
        from decimal import Decimal
        paid = self.treatment.payments.filter(type=self.TYPE_INCOME).aggregate(s=Sum("amount"))["s"] or Decimal(0)
        refund = self.treatment.payments.filter(type=self.TYPE_REFUND).aggregate(s=Sum("amount"))["s"] or Decimal(0)
        from apps.treatments.models import Treatment
        Treatment.objects.filter(pk=self.treatment_id).update(paid_amount=paid - refund)


class Expense(ClinicScopedModel):
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses", verbose_name="Категория")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Сумма")
    description = models.TextField(verbose_name="Описание")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="expenses", verbose_name="Филиал")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses", verbose_name="Создал"
    )
    date = models.DateField(verbose_name="Дата")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.category} — {self.amount} сом [{self.date}]"


class PatientAdvance(models.Model):
    """Pre-payment / deposit."""

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="advances", verbose_name="Пациент")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Сумма")
    date = models.DateField(verbose_name="Дата")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Предоплата"
        verbose_name_plural = "Предоплаты"

    def __str__(self):
        return f"{self.patient} — аванс {self.amount} [{self.date}]"
