from django.db import models
from apps.services.models import Service


class Technician(models.Model):
    name = models.CharField(max_length=200, verbose_name="ФИО")
    phone = models.CharField(max_length=30, verbose_name="Телефон")
    services = models.ManyToManyField(
        Service,
        through="TechnicianAgreement",
        blank=True,
        verbose_name="Услуги",
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Баланс")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Техник"
        verbose_name_plural = "Технические специалисты"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TechnicianAgreement(models.Model):
    """Price agreement between clinic and a dental lab technician."""

    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="agreements")
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="technician_agreements")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Цена договора")

    class Meta:
        verbose_name = "Договор с техником"
        verbose_name_plural = "Договоры с техниками"
        unique_together = [["technician", "service"]]

    def __str__(self):
        return f"{self.technician} — {self.service}: {self.price}"


class TechnicianTask(models.Model):
    STATUS_CHOICES = [
        ("pending", "Ожидает"),
        ("in_progress", "В работе"),
        ("done", "Готово"),
    ]

    technician = models.ForeignKey(Technician, on_delete=models.PROTECT, related_name="tech_tasks")
    treatment = models.ForeignKey("treatments.Treatment", on_delete=models.PROTECT, related_name="tech_tasks")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="tech_tasks")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Стоимость работы")
    deadline = models.DateField(null=True, blank=True, verbose_name="Срок")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Задание технику"
        verbose_name_plural = "Задания техникам"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.technician} — {self.service} [{self.get_status_display()}]"
