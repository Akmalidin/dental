"""Salary scheme and payroll reports."""
from django.db import models
from django.conf import settings


class SalaryScheme(models.Model):
    TYPE_FIXED = "fixed"
    TYPE_PERCENT_REVENUE = "percent_revenue"
    TYPE_PERCENT_PAID = "percent_paid"
    TYPE_COMBINED = "combined"

    TYPE_CHOICES = [
        (TYPE_FIXED, "Фиксированная ставка"),
        (TYPE_PERCENT_REVENUE, "% от выручки"),
        (TYPE_PERCENT_PAID, "% от оплат (кассовый)"),
        (TYPE_COMBINED, "Ставка + %"),
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
        return 0


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
