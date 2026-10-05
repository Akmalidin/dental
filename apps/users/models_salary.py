"""Salary scheme and payroll reports."""
from django.db import models
from django.conf import settings

from apps.tenancy import ClinicScopedModel


class SalaryScheme(models.Model):
    TYPE_FIXED = "fixed"
    TYPE_PERCENT_REVENUE = "percent_revenue"
    TYPE_PERCENT_PAID = "percent_paid"
    TYPE_COMBINED = "combined"
    TYPE_PERCENT_SERVICE = "percent_service"

    TYPE_CHOICES = [
        (TYPE_FIXED, "Фиксированная ставка"),
        (TYPE_PERCENT_REVENUE, "% от выручки"),
        (TYPE_PERCENT_PAID, "% от оплат (кассовый)"),
        (TYPE_COMBINED, "Ставка + %"),
        (TYPE_PERCENT_SERVICE, "% от услуги (по категориям)"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="salary_scheme",
        verbose_name="Сотрудник",
    )
    scheme_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_FIXED, verbose_name="Схема")
    fixed_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Фиксированная ставка (сом/мес)"
    )
    percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Процент (%)")
    description = models.CharField(max_length=300, blank=True, verbose_name="Описание")

    class Meta:
        verbose_name = "Схема зарплаты"
        verbose_name_plural = "Схемы зарплат"

    def __str__(self):
        return f"{self.user.name} — {self.get_scheme_type_display()}"

    def calculate(self, revenue: float = 0, paid: float = 0) -> float:
        """Calculate salary based on scheme."""
        from decimal import Decimal
        rev = Decimal(str(revenue))
        pmt = Decimal(str(paid))
        if self.scheme_type == self.TYPE_FIXED:
            return float(self.fixed_amount)
        elif self.scheme_type == self.TYPE_PERCENT_REVENUE:
            return float(rev * self.percent / 100)
        elif self.scheme_type == self.TYPE_PERCENT_PAID:
            return float(pmt * self.percent / 100)
        elif self.scheme_type == self.TYPE_COMBINED:
            return float(self.fixed_amount + rev * self.percent / 100)
        # TYPE_PERCENT_SERVICE считается по каждой оплате и услуге —
        # apps.users.salary_calc.service_salary, а не по общим суммам.
        return 0

    def percent_for_category(self, category_id):
        """Процент для категории услуги; для остальных — общий percent."""
        if category_id is not None:
            for cp in self.category_percents.all():
                if cp.category_id == category_id:
                    return cp.percent
        return self.percent


class SalaryCategoryPercent(models.Model):
    """Схема «% от услуги»: свой процент для категории услуг."""

    scheme = models.ForeignKey(SalaryScheme, on_delete=models.CASCADE, related_name="category_percents")
    category = models.ForeignKey(
        "services.ServiceCategory", on_delete=models.CASCADE, related_name="+", verbose_name="Категория",
    )
    percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Процент (%)")

    class Meta:
        verbose_name = "Процент по категории"
        verbose_name_plural = "Проценты по категориям"
        unique_together = [["scheme", "category"]]

    def __str__(self):
        return f"{self.scheme_id}: {self.category_id} — {self.percent}%"


class SalaryPayout(ClinicScopedModel):
    """Выплата зарплаты сотруднику. Только фиксируется — расходом в кассе
    не проводится."""

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="salary_payouts",
        verbose_name="Сотрудник",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Сумма")
    paid_on = models.DateField(verbose_name="Дата выплаты")
    # За какой период выплата — от него считается «Не выплачено с …».
    period_from = models.DateField(null=True, blank=True, verbose_name="Период с")
    period_to = models.DateField(null=True, blank=True, verbose_name="Период по")
    comment = models.CharField(max_length=300, blank=True, verbose_name="Комментарий")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Выплата зарплаты"
        verbose_name_plural = "Выплаты зарплаты"
        ordering = ["-paid_on", "-id"]

    def __str__(self):
        return f"{self.doctor_id}: {self.amount} [{self.paid_on}]"


class DoctorSchedule(models.Model):
    """Weekly work schedule per doctor/branch."""

    DAY_CHOICES = [
        (0, "Понедельник"), (1, "Вторник"), (2, "Среда"),
        (3, "Четверг"), (4, "Пятница"), (5, "Суббота"), (6, "Воскресенье"),
    ]

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="schedules", verbose_name="Врач"
    )
    branch = models.ForeignKey(
        "users.Branch", on_delete=models.CASCADE, related_name="schedules", verbose_name="Филиал"
    )
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES, verbose_name="День недели")
    start_time = models.TimeField(verbose_name="Начало работы")
    end_time = models.TimeField(verbose_name="Конец работы")
    is_working = models.BooleanField(default=True, verbose_name="Рабочий день")

    class Meta:
        verbose_name = "График работы"
        verbose_name_plural = "Графики работы"
        ordering = ["doctor", "day_of_week"]
        unique_together = [["doctor", "branch", "day_of_week"]]

    def __str__(self):
        return f"{self.doctor.name} — {self.get_day_of_week_display()}: {self.start_time}–{self.end_time}"
