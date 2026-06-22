from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from apps.services.models import Service
from apps.tenancy import ClinicScopedModel


class Technician(ClinicScopedModel):
    SPEC_CHOICES = [
        ("ceramic", "Металлокерамика"),
        ("zirconia", "Цирконий"),
        ("removable", "Съёмные протезы"),
        ("implant", "Импланты"),
        ("ortho", "Ортодонтия (каппы, пластинки)"),
        ("combined", "Комбинированная"),
        ("other", "Другое"),
    ]

    name = models.CharField(max_length=200, verbose_name="ФИО")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Телефон")
    lab_name = models.CharField(max_length=200, blank=True, verbose_name="Лаборатория")
    lab_contact = models.CharField(max_length=200, blank=True, verbose_name="Контакт лаборатории")
    specialization = models.CharField(max_length=20, choices=SPEC_CHOICES, blank=True, verbose_name="Специализация")
    default_lead_days = models.PositiveIntegerField(default=5, verbose_name="Срок изготовления по умолчанию (дней)")
    services = models.ManyToManyField(
        Service, through="TechnicianAgreement", blank=True, verbose_name="Услуги",
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Баланс")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Техник"
        verbose_name_plural = "Технические специалисты"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TechnicianAgreement(models.Model):
    """Прайс техника на конкретную услугу (себестоимость для клиники)."""

    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="agreements")
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="technician_agreements")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Цена договора")

    class Meta:
        verbose_name = "Договор с техником"
        verbose_name_plural = "Договоры с техниками"
        unique_together = [["technician", "service"]]

    def __str__(self):
        return f"{self.technician} — {self.service}: {self.price}"


class TechnicianTask(ClinicScopedModel):
    """Заказ зуботехнической работы (коронка, протез и т.д.)."""
    STATUS_TRANSFERRED = "transferred"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_READY = "ready"
    STATUS_FITTING = "fitting"
    STATUS_CORRECTION = "correction"
    STATUS_INSTALLED = "installed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_TRANSFERRED, "Передан в работу"),
        (STATUS_IN_PROGRESS, "В изготовлении"),
        (STATUS_READY, "Готов"),
        (STATUS_FITTING, "Примерка"),
        (STATUS_CORRECTION, "Коррекция"),
        (STATUS_INSTALLED, "Установлено"),
        (STATUS_CANCELLED, "Отменено"),
    ]
    OPEN_STATUSES = (STATUS_TRANSFERRED, STATUS_IN_PROGRESS, STATUS_FITTING, STATUS_CORRECTION)

    technician = models.ForeignKey(Technician, on_delete=models.PROTECT, related_name="tech_tasks")
    treatment = models.ForeignKey("treatments.Treatment", on_delete=models.PROTECT, related_name="tech_tasks")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, null=True, blank=True, related_name="tech_orders")
    cure = models.OneToOneField(
        "treatments.TreatmentCure", on_delete=models.SET_NULL, null=True, blank=True, related_name="lab_order_obj"
    )
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="tech_tasks")
    tooth_number = models.CharField(max_length=120, blank=True, verbose_name="Зуб")
    material = models.CharField(max_length=120, blank=True, verbose_name="Материал / тип работы")
    vita_color = models.CharField(max_length=20, blank=True, verbose_name="Цвет (Vita)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TRANSFERRED, verbose_name="Статус")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Стоимость работы техника")
    doctor_comment = models.TextField(blank=True, verbose_name="Комментарий врача технику")

    transferred_at = models.DateField(null=True, blank=True, verbose_name="Передан в работу")
    expected_ready = models.DateField(null=True, blank=True, verbose_name="Ожидаемая готовность")
    ready_at = models.DateField(null=True, blank=True, verbose_name="Готов (факт)")
    installed_at = models.DateField(null=True, blank=True, verbose_name="Установлено")
    warranty_until = models.DateField(null=True, blank=True, verbose_name="Гарантия до")

    paid = models.BooleanField(default=False, verbose_name="Оплачено технику")
    paid_at = models.DateField(null=True, blank=True)
    expense = models.ForeignKey(
        "finance.Expense", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    deadline = models.DateField(null=True, blank=True, verbose_name="Срок")  # legacy
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Заказ технику"
        verbose_name_plural = "Заказы техникам"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Заказ #{self.pk} — {self.service} ({self.get_status_display()})"

    @property
    def is_overdue(self):
        return bool(self.expected_ready and self.status in self.OPEN_STATUSES
                    and self.expected_ready < timezone.localdate())

    def compute_warranty(self):
        """Дата окончания гарантии = дата установки + гарантия услуги (мес)."""
        months = getattr(self.service, "warranty_months", 0) or 0
        base = self.installed_at or timezone.localdate()
        if months:
            return base + timedelta(days=int(months * 30.4))
        return None


class TechnicianOrderEvent(models.Model):
    """Журнал смены статусов заказа — чтобы видеть длительность каждого этапа."""
    task = models.ForeignKey(TechnicianTask, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=TechnicianTask.STATUS_CHOICES)
    at = models.DateTimeField(auto_now_add=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["at"]


class TechnicianOrderFile(models.Model):
    """Файлы заказа: фото слепка, готового изделия, 3D-скан."""
    task = models.ForeignKey(TechnicianTask, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="tech_orders/%Y/%m/")
    name = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_image(self):
        n = (self.file.name or "").lower()
        return n.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))


class TechnicianWarrantyCase(ClinicScopedModel):
    """Гарантийный случай: изделие вернулось с жалобой в гарантийный срок."""
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="warranty_cases")
    task = models.ForeignKey(TechnicianTask, on_delete=models.SET_NULL, null=True, blank=True, related_name="warranty_cases")
    patient = models.ForeignKey("patients.Patient", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reason = models.TextField(verbose_name="Причина обращения")
    resolved = models.BooleanField(default=False, verbose_name="Решено")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "Гарантийный случай"
        verbose_name_plural = "Гарантийные случаи"
        ordering = ["-created_at"]
