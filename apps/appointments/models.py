from django.db import models
from django.conf import settings
from apps.users.models import Branch
from apps.patients.models import Patient
from apps.services.models import Service
from apps.tenancy import ClinicSoftDeleteModel


class CancellationReason(models.Model):
    """Reusable reasons for cancelling an appointment (managed in settings)."""

    name = models.CharField(max_length=200, verbose_name="Причина отмены")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Причина отмены"
        verbose_name_plural = "Причины отмены"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Cabinet(models.Model):
    """Treatment room / chair."""

    name = models.CharField(max_length=100, verbose_name="Кабинет")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="cabinets")
    color = models.CharField(max_length=7, default="#10B981", verbose_name="Цвет")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Кабинет"
        verbose_name_plural = "Кабинеты"
        ordering = ["branch", "name"]

    def __str__(self):
        return f"{self.branch} — {self.name}"


class Appointment(ClinicSoftDeleteModel):
    STATUS_SCHEDULED = "scheduled"
    STATUS_CONFIRMED = "confirmed"
    STATUS_ARRIVED = "arrived"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_NO_SHOW = "no_show"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Записан"),
        (STATUS_CONFIRMED, "Подтверждён"),
        (STATUS_ARRIVED, "Пришёл"),
        (STATUS_IN_PROGRESS, "Принимается"),
        (STATUS_COMPLETED, "Завершён"),
        (STATUS_NO_SHOW, "Не пришёл"),
        (STATUS_CANCELLED, "Отменён"),
    ]

    SOURCE_CHOICES = [
        ("manual", "Вручную"),
        ("online", "Онлайн"),
        ("telegram", "Telegram"),
        ("whatsapp", "WhatsApp"),
        ("ai", "ИИ-ассистент"),
    ]

    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="Пациент",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name="Врач",
    )
    cabinet = models.ForeignKey(
        Cabinet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="Кабинет",
    )
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="appointments", verbose_name="Филиал")
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="Услуга (основная)",
    )
    services = models.ManyToManyField(
        Service, blank=True, related_name="appointments_multi", verbose_name="Услуги",
    )
    start_at = models.DateTimeField(verbose_name="Начало")
    end_at = models.DateTimeField(verbose_name="Конец")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED, verbose_name="Статус")
    cancellation_reason = models.ForeignKey(
        "appointments.CancellationReason", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="appointments", verbose_name="Причина отмены",
    )
    cancel_note = models.CharField(max_length=300, blank=True, verbose_name="Комментарий к отмене")
    notes = models.TextField(blank=True, verbose_name="Заметки")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="manual", verbose_name="Источник")
    # Время приёма, о котором врачу уже напомнили в Telegram (за ~30 минут).
    # Храним само время, а не флаг: при переносе записи напоминание придёт снова.
    doctor_reminded_for = models.DateTimeField(null=True, blank=True, editable=False)
    reminded_day = models.BooleanField(default=False)   # отправлено напоминание за день
    reminded_hour = models.BooleanField(default=False)  # отправлено напоминание за час
    overdue_notified = models.BooleanField(default=False)  # уведомление о просроченном визите отправлено
    gcal_event_id = models.CharField(max_length=200, blank=True, verbose_name="ID события Google Calendar")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_appointments",
    )

    class Meta:
        verbose_name = "Запись"
        verbose_name_plural = "Записи"
        ordering = ["start_at"]
        base_manager_name = "all_objects"

    def __str__(self):
        patient_name = self.patient.full_name if self.patient else "—"
        return f"{patient_name} → {self.doctor} [{self.start_at:%d.%m %H:%M}]"

    @classmethod
    def from_db(cls, db, field_names, values):
        obj = super().from_db(db, field_names, values)
        obj._loaded_start_at = obj.__dict__.get("start_at")
        return obj

    def save(self, *args, **kwargs):
        # Перенос записи на другое время → напоминания о новом времени должны
        # прийти заново (флаги «уже напомнили» относились к старому времени).
        loaded = getattr(self, "_loaded_start_at", None)
        if self.pk and loaded is not None and self.start_at and self.start_at != loaded:
            self.reminded_day = self.reminded_hour = self.overdue_notified = False
            fields = kwargs.get("update_fields")
            if fields is not None:
                kwargs["update_fields"] = set(fields) | {"reminded_day", "reminded_hour", "overdue_notified"}
        super().save(*args, **kwargs)
        self._loaded_start_at = self.start_at

    @property
    def duration_minutes(self):
        delta = self.end_at - self.start_at
        return int(delta.total_seconds() / 60)


from apps.tenancy import ClinicScopedModel  # noqa: E402


class WaitlistEntry(ClinicScopedModel):
    """Лист ожидания: пациент хочет попасть раньше / на занятое время.
    Когда запись отменяют или переносят, освободившееся окно сверяется с
    листом (apps.appointments.waitlist.match) — администратор получает
    уведомление и в один клик записывает или предлагает время пациенту."""

    STATUS_WAITING = "waiting"
    STATUS_OFFERED = "offered"
    STATUS_BOOKED = "booked"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_WAITING, "Ждёт"),
        (STATUS_OFFERED, "Предложено"),
        (STATUS_BOOKED, "Записан"),
        (STATUS_CANCELLED, "Снят"),
    ]
    PART_ANY, PART_MORNING, PART_DAY, PART_EVENING = "any", "morning", "day", "evening"
    PART_CHOICES = [
        (PART_ANY, "Любое время"),
        (PART_MORNING, "Утро (до 12:00)"),
        (PART_DAY, "День (12:00–16:00)"),
        (PART_EVENING, "Вечер (после 16:00)"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="waitlist_entries",
                                verbose_name="Пациент")
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+", verbose_name="Врач (пусто — любой)")
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+", verbose_name="Услуга")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+", verbose_name="Филиал (пусто — любой)")
    date_from = models.DateField(null=True, blank=True, verbose_name="С даты")
    date_to = models.DateField(null=True, blank=True, verbose_name="По дату")
    part_of_day = models.CharField(max_length=10, choices=PART_CHOICES, default=PART_ANY,
                                   verbose_name="Время дня")
    duration_min = models.PositiveIntegerField(default=30, verbose_name="Длительность, мин")
    urgent = models.BooleanField(default=False, verbose_name="Срочно (боль)")
    note = models.CharField(max_length=500, blank=True, verbose_name="Комментарий")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_WAITING,
                              db_index=True, verbose_name="Статус")
    offered_at = models.DateTimeField(null=True, blank=True)
    offered_start = models.DateTimeField(null=True, blank=True, verbose_name="Предложенное время")
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="Запись")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Лист ожидания"
        verbose_name_plural = "Лист ожидания"
        ordering = ["-urgent", "created_at"]

    def __str__(self):
        return f"{self.patient_id}: {self.get_status_display()}"
