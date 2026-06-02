from django.db import models
from django.conf import settings
from apps.patients.models import Patient


class Medicine(models.Model):
    FORM_CHOICES = [
        ("tablets", "Таблетки"),
        ("capsules", "Капсулы"),
        ("drops", "Капли"),
        ("ointment", "Мазь"),
        ("solution", "Раствор"),
        ("other", "Другое"),
    ]

    name = models.CharField(max_length=200, verbose_name="Лекарство")
    form = models.CharField(max_length=20, choices=FORM_CHOICES, default="tablets", verbose_name="Форма")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Остаток")
    unit = models.CharField(max_length=30, verbose_name="Единица")
    min_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Мин. остаток")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Лекарство"
        verbose_name_plural = "Лекарства"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_form_display()})"


class PatientMedicine(models.Model):
    """Prescription / medicine assignment to patient."""

    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="medicines", verbose_name="Пациент"
    )
    treatment = models.ForeignKey(
        "treatments.Treatment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="medicines",
        verbose_name="Приём",
    )
    medicine = models.ForeignKey(
        Medicine, on_delete=models.PROTECT, related_name="prescriptions", verbose_name="Лекарство"
    )
    dosage = models.CharField(max_length=200, verbose_name="Дозировка")
    duration = models.CharField(max_length=100, verbose_name="Длительность")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="prescriptions",
        verbose_name="Врач",
    )
    date = models.DateField(verbose_name="Дата назначения")
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Назначение лекарства"
        verbose_name_plural = "Назначения лекарств"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.patient} — {self.medicine} [{self.date}]"
