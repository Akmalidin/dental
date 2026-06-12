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

    # Порядковый номер пациента ВНУТРИ клиники (у каждой клиники нумерация с 1).
    # Не путать с глобальным pk (id в БД).
    number = models.PositiveIntegerField(
        null=True, blank=True, db_index=True, verbose_name="№ пациента",
    )

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
    last_debt_reminder = models.DateTimeField(null=True, blank=True, verbose_name="Последнее напоминание о долге")
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

    def save(self, *args, **kwargs):
        # Назначаем порядковый номер в пределах клиники при первом сохранении.
        # _ClinicSaveMixin.save (через super) проставит clinic; нам он нужен заранее,
        # поэтому повторяем его логику здесь для расчёта номера.
        if self.number is None:
            from apps.tenancy import get_current_clinic
            from django.db.models import Max
            if self.clinic_id is None:
                cur = get_current_clinic()
                if cur is not None:
                    self.clinic = cur
            if self.clinic_id is not None:
                last = (Patient.all_objects.filter(clinic_id=self.clinic_id)
                        .aggregate(m=Max("number"))["m"] or 0)
                self.number = last + 1
        super().save(*args, **kwargs)

    @property
    def display_number(self):
        """Номер для показа: порядковый в клинике, иначе глобальный id."""
        return self.number or self.pk

    def related_summary(self):
        """Счётчики связанных данных — для предупреждения перед безвозвратным удалением."""
        from apps.treatments.models import Treatment
        from apps.treatments.models_plan import TreatmentPlan
        from apps.finance.models import Payment, PatientAdvance
        from apps.medicines.models import PatientMedicine
        from apps.appointments.models import Appointment
        pid = self.pk
        return {
            "treatments": Treatment._base_manager.filter(patient_id=pid).count(),
            "plans": TreatmentPlan._base_manager.filter(patient_id=pid).count(),
            "payments": Payment._base_manager.filter(patient_id=pid).count(),
            "advances": PatientAdvance._base_manager.filter(patient_id=pid).count(),
            "medicines": PatientMedicine._base_manager.filter(patient_id=pid).count(),
            "appointments": Appointment._base_manager.filter(patient_id=pid).count(),
            "debt": self.debt,
        }

    def has_related_data(self):
        s = self.related_summary()
        return any(s[k] for k in ("treatments", "plans", "payments", "advances", "medicines", "appointments"))

    def purge_with_related(self):
        """Безвозвратно удалить пациента и ВСЕ связанные данные (в одной транзакции).
        Порядок важен: сначала записи с on_delete=PROTECT (платежи, приёмы, планы),
        иначе БД не даст удалить пациента."""
        from django.db import transaction
        from apps.treatments.models import Treatment
        from apps.treatments.models_plan import TreatmentPlan
        from apps.finance.models import Payment, PatientAdvance
        from apps.medicines.models import PatientMedicine
        from apps.appointments.models import Appointment
        pid = self.pk
        with transaction.atomic():
            # платежи раньше приёмов: Payment.treatment = PROTECT
            Payment._base_manager.filter(patient_id=pid).delete()
            PatientAdvance._base_manager.filter(patient_id=pid).delete()
            PatientMedicine._base_manager.filter(patient_id=pid).delete()
            TreatmentPlan._base_manager.filter(patient_id=pid).delete()   # каскадом — этапы/пункты
            Treatment._base_manager.filter(patient_id=pid).delete()       # каскадом — процедуры/файлы
            Appointment._base_manager.filter(patient_id=pid).delete()
            # tooth_conditions / medical_records / wa_messages удалятся каскадом (CASCADE)
            Patient._base_manager.filter(pk=pid).delete()

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

    def recalc_balance(self):
        """Пересчитать баланс пациента: платежи − возвраты − (сумма приёмов − скидки).
        Считается по всем клиникам (минуя фильтр текущей клиники), отменённые приёмы не в счёт.
        """
        from django.db.models import Sum
        from decimal import Decimal
        from apps.finance.models import Payment
        from apps.treatments.models import Treatment
        income = (Payment.all_clinics.filter(patient_id=self.pk, type=Payment.TYPE_INCOME)
                  .aggregate(s=Sum("amount"))["s"] or Decimal(0))
        refund = (Payment.all_clinics.filter(patient_id=self.pk, type=Payment.TYPE_REFUND)
                  .aggregate(s=Sum("amount"))["s"] or Decimal(0))
        agg = (Treatment.all_objects.filter(patient_id=self.pk, is_deleted=False)
               .exclude(status="cancelled").aggregate(tot=Sum("total_amount"), disc=Sum("discount")))
        treatments_total = agg["tot"] or Decimal(0)
        discount_total = agg["disc"] or Decimal(0)
        balance = income - refund - (treatments_total - discount_total)
        Patient.all_objects.filter(pk=self.pk).update(balance=balance)
        self.balance = balance
        return balance
