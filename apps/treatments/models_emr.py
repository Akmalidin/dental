"""Electronic Medical Record (ЭМК) — templates + per-visit records."""
from django.db import models
from django.conf import settings
from apps.tenancy import ClinicScopedModel


# Sections of a dental medical record
EMR_SECTIONS = [
    ("complaints", "Жалобы"),
    ("anamnesis", "Анамнез заболевания"),
    ("external_exam", "Внешний осмотр"),
    ("objective", "Объективно"),
    ("diagnosis", "Диагноз"),
    ("treatment", "Лечение"),
    ("recommendations", "Рекомендации"),
]


class MedicalRecordTemplate(ClinicScopedModel):
    """Reusable EMR template (e.g. «Средний кариес»)."""

    name = models.CharField(max_length=300, verbose_name="Название")
    complaints = models.TextField(blank=True, verbose_name="Жалобы")
    anamnesis = models.TextField(blank=True, verbose_name="Анамнез")
    external_exam = models.TextField(blank=True, verbose_name="Внешний осмотр")
    objective = models.TextField(blank=True, verbose_name="Объективно")
    diagnosis = models.TextField(blank=True, verbose_name="Диагноз")
    treatment = models.TextField(blank=True, verbose_name="Лечение")
    recommendations = models.TextField(blank=True, verbose_name="Рекомендации")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Шаблон ЭМК"
        verbose_name_plural = "Шаблоны ЭМК"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def as_dict(self):
        return {k: getattr(self, k) for k, _ in EMR_SECTIONS}


class MedicalRecord(models.Model):
    """The filled medical record for a specific visit (treatment)."""

    treatment = models.OneToOneField(
        "treatments.Treatment", on_delete=models.CASCADE, related_name="emr", verbose_name="Приём"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="medical_records", verbose_name="Пациент"
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="medical_records"
    )
    complaints = models.TextField(blank=True, verbose_name="Жалобы")
    anamnesis = models.TextField(blank=True, verbose_name="Анамнез")
    external_exam = models.TextField(blank=True, verbose_name="Внешний осмотр")
    objective = models.TextField(blank=True, verbose_name="Объективно")
    diagnosis = models.TextField(blank=True, verbose_name="Диагноз")
    treatment_text = models.TextField(blank=True, verbose_name="Лечение")
    recommendations = models.TextField(blank=True, verbose_name="Рекомендации")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Медкарта (ЭМК)"
        verbose_name_plural = "Медкарты (ЭМК)"

    def __str__(self):
        return f"ЭМК приёма #{self.treatment_id}"
