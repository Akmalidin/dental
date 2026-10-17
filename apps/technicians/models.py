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
    # Логин техника: с ним он входит в свой кабинет (/new/lab/my/) и видит
    # только свои заказы и выплаты. Один логин может быть техником в
    # нескольких клиниках (подключение по коду техника, TechnicianCode) —
    # по одной записи Technician в каждой.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="technician_profiles", verbose_name="Учётная запись для входа",
    )

    class Meta:
        verbose_name = "Техник"
        verbose_name_plural = "Технические специалисты"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["clinic", "user"], condition=models.Q(user__isnull=False),
                                               name="technician_one_per_clinic_user")]

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


class TechnicianOrderMessage(models.Model):
    """Переписка по заказу между техником и клиникой и запросы техника
    перенести срок (kind=deadline): клиника подтверждает — срок меняется."""
    KIND_COMMENT = "comment"
    KIND_DEADLINE = "deadline"
    KIND_CHOICES = [(KIND_COMMENT, "Комментарий"), (KIND_DEADLINE, "Запрос нового срока")]
    PENDING, APPROVED, DECLINED = "pending", "approved", "declined"
    DECISION_CHOICES = [(PENDING, "Ждёт решения"), (APPROVED, "Срок перенесён"), (DECLINED, "Отклонено")]

    task = models.ForeignKey(TechnicianTask, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    from_technician = models.BooleanField(default=False)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_COMMENT)
    text = models.TextField(blank=True)
    old_date = models.DateField(null=True, blank=True)
    proposed_date = models.DateField(null=True, blank=True)
    decision = models.CharField(max_length=10, choices=DECISION_CHOICES, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class _CompressPhotoOnSave:
    """Фото (слепок, цвет, готовая работа) сжимаются при загрузке так же, как
    фото в карте приёма: до 2560 px, JPEG 85. 3D-сканы, PDF и прочие не-картинки
    сохраняются как есть (compress_photo вернёт None)."""

    def save(self, *args, **kwargs):
        if self._state.adding and self.file and not getattr(self.file, "_committed", True):
            from apps.treatments.image_compress import compress_photo
            small = compress_photo(self.file)
            if small is not None:
                self.file = small
        super().save(*args, **kwargs)


class TechnicianOrderFile(_CompressPhotoOnSave, models.Model):
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


class TechnicianCode(models.Model):
    """Код техника: техник сообщает его другой клинике, её администратор
    вводит код — и техник подключается к этой клинике (своя запись Technician
    там, заказы приходят в тот же кабинет)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="technician_code")
    code = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


# ─── Заказы от клиник, которые не работают в ODONTIS ─────────────────────────
# Техник ведёт их сам в своём кабинете. Принадлежат логину техника (owner),
# а не клинике: клиника их не видит.

class ExternalClinic(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lab_external_clinics")
    name = models.CharField(max_length=200, verbose_name="Клиника")
    phone = models.CharField(max_length=40, blank=True)
    contact = models.CharField(max_length=200, blank=True, verbose_name="Контакт / адрес")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ExternalOrder(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lab_external_orders")
    clinic = models.ForeignKey(ExternalClinic, on_delete=models.CASCADE, related_name="orders")
    patient_name = models.CharField(max_length=200, blank=True)
    doctor_name = models.CharField(max_length=200, blank=True)
    work = models.CharField(max_length=200, verbose_name="Работа")
    tooth_number = models.CharField(max_length=120, blank=True)
    material = models.CharField(max_length=120, blank=True)
    vita_color = models.CharField(max_length=20, blank=True)
    comment = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=TechnicianTask.STATUS_CHOICES,
                              default=TechnicianTask.STATUS_TRANSFERRED)
    transferred_at = models.DateField(null=True, blank=True)
    expected_ready = models.DateField(null=True, blank=True)
    ready_at = models.DateField(null=True, blank=True)
    installed_at = models.DateField(null=True, blank=True)
    paid = models.BooleanField(default=False)
    paid_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_overdue(self):
        return bool(self.expected_ready and self.status in TechnicianTask.OPEN_STATUSES
                    and self.expected_ready < timezone.localdate())


class ExternalOrderFile(_CompressPhotoOnSave, models.Model):
    order = models.ForeignKey(ExternalOrder, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="tech_orders/ext/%Y/%m/")
    name = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_image(self):
        n = (self.file.name or "").lower()
        return n.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))
