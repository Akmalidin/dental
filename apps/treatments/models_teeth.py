"""
Статусы зубной карты (справочник состояний зуба) и состояние зубов пациента.
"""
from django.db import models
from django.conf import settings


# Дефолтные статусы: (код, название, цвет HEX)
DEFAULT_TOOTH_STATUSES = [
    ("healthy", "Здоров", "#22C55E"),
    ("caries", "Кариес", "#F59E0B"),
    ("filling", "Пломба", "#3B82F6"),
    ("root_canal", "Лечён канал", "#8B5CF6"),
    ("crown", "Коронка", "#EAB308"),
    ("implant", "Имплант", "#06B6D4"),
    ("bridge", "Мост", "#14B8A6"),
    ("to_remove", "Подлежит удалению", "#F97316"),
    ("missing", "Отсутствует / удалён", "#EF4444"),
]


class ToothStatus(models.Model):
    """Справочник состояний зуба с цветом."""
    code = models.CharField(max_length=40, blank=True, verbose_name="Код")
    name = models.CharField(max_length=80, verbose_name="Название")
    color = models.CharField(max_length=9, default="#6366F1", verbose_name="Цвет")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Статус зуба"
        verbose_name_plural = "Статусы зубов"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class ToothCondition(models.Model):
    """Текущее состояние конкретного зуба у пациента."""
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="tooth_conditions"
    )
    tooth_number = models.PositiveSmallIntegerField(verbose_name="Зуб (FDI)")
    status = models.ForeignKey(
        ToothStatus, on_delete=models.SET_NULL, null=True, blank=True, related_name="conditions"
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="Заметка")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = "Состояние зуба"
        verbose_name_plural = "Состояния зубов"
        unique_together = [("patient", "tooth_number")]
        ordering = ["tooth_number"]

    def __str__(self):
        return f"{self.patient_id} · зуб {self.tooth_number}"
