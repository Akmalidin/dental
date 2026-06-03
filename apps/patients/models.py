from django.db import models
from django.conf import settings
from simple_history.models import HistoricalRecords
from apps.users.models import Branch
from apps.tenancy import ClinicSoftDeleteModel
from .models_insurance import InsuranceCompany  # noqa: F401 — re-exported


class LeadSource(models.Model):
    """Where the patient came from (Instagram, ads, referral, etc.)."""

    name = models.CharField(max_length=100, verbose_name="Источник")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Источник пациента"
        verbose_name_plural = "Источники пациентов"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=80, verbose_name="Тег")
    color = models.CharField(max_length=7, default="#3B82F6", verbose_name="Цвет (hex)")

    class Meta:
        verbose_name = "Тег"
        verbose_name_plural = "Теги"

    def __str__(self):
        return self.name


class Patient(ClinicSoftDeleteModel):
    GENDER_CHOICES = [("male", "Мужской"), ("female", "Женский")]

    first_name = models.CharField(max_length=100, verbose_name="Имя")
    last_name = models.CharField(max_length=100, verbose_name="Фамилия")
    middle_name = models.CharField(max_length=100, blank=True, verbose_name="Отчество")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Дата рождения")
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, verbose_name="Пол")
    phone = models.CharField(max_length=30, verbose_name="Телефон")
    phone2 = models.CharField(max_length=30, blank=True, verbose_name="Доп. телефон")
    address = models.CharField(max_length=500, blank=True, verbose_name="Адрес")
    source = models.ForeignKey(
        LeadSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patients",
        verbose_name="Источник",
    )
    tags = models.ManyToManyField(Tag, blank=True, verbose_name="Теги")
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="patients",
        verbose_name="Филиал",
    )
    # Insurance / DMS
    insurance = models.ForeignKey(
        "patients.InsuranceCompany",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="patients",
        verbose_name="Страховая компания",
    )
    insurance_policy = models.CharField(max_length=100, blank=True, verbose_name="Номер полиса ДМС")
    insurance_valid_until = models.DateField(null=True, blank=True, verbose_name="Полис действует до")

    # Treating doctor
    primary_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="primary_patients",
        verbose_name="Лечащий врач",
    )

    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Баланс (сом)")
    notes = models.TextField(blank=True, verbose_name="Заметки")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_patients",
        verbose_name="Создал",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Пациент"
        verbose_name_plural = "Пациенты"
        ordering = ["-created_at"]
        base_manager_name = "all_objects"

    def __str__(self):
        return f"{self.last_name} {self.first_name}"

    @property
    def full_name(self):
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(p for p in parts if p)

    @property
    def age(self):
        if not self.birth_date:
            return None
        from datetime import date
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def debt(self):
        from django.db.models import Sum
        from decimal import Decimal
        # отменённые приёмы не создают долг
        qs = self.treatments.exclude(status="cancelled")
        total = qs.aggregate(total=Sum("total_amount"))["total"] or Decimal(0)
        disc = qs.aggregate(disc=Sum("discount"))["disc"] or Decimal(0)
        paid = qs.aggregate(paid=Sum("paid_amount"))["paid"] or Decimal(0)
        return max(Decimal(0), total - disc - paid)
