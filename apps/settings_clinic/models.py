from django.db import models
from .models_documents import DocumentTemplate  # noqa: F401


class ClinicSettings(models.Model):
    """Per-tenant clinic configuration (singleton)."""

    clinic = models.OneToOneField(
        "users.Clinic", on_delete=models.CASCADE, null=True, blank=True,
        related_name="settings", verbose_name="Клиника",
    )
    logo = models.ImageField(upload_to="clinic/", null=True, blank=True, verbose_name="Логотип")
    name = models.CharField(max_length=200, verbose_name="Название клиники")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Телефон")
    address = models.CharField(max_length=500, blank=True, verbose_name="Адрес")
    working_hours = models.JSONField(
        default=dict,
        verbose_name="Рабочие часы",
        help_text='{"mon": ["09:00","18:00"], "tue": ["09:00","18:00"], ...}',
    )
    appointment_slot = models.PositiveIntegerField(default=30, verbose_name="Слот записи (мин)")
    currency = models.CharField(max_length=10, default="KGS", verbose_name="Валюта")
    language = models.CharField(max_length=5, default="ru", verbose_name="Язык")
    require_unique_phone = models.BooleanField(default=True, verbose_name="Уникальный телефон")
    telegram_bot_token = models.CharField(max_length=200, blank=True, verbose_name="Telegram Bot Token")
    # WhatsApp авто-напоминания
    wa_remind_day = models.BooleanField(default=True, verbose_name="Напоминать за день до приёма")
    wa_remind_hour = models.BooleanField(default=True, verbose_name="Напоминать за час до приёма")
    wa_remind_debt_days = models.PositiveIntegerField(default=7, verbose_name="Напоминать должникам каждые N дней (0 — выкл)")
    # Tariff / feature flags: list of enabled module keys. Empty = all enabled.
    enabled_modules = models.JSONField(default=list, blank=True, verbose_name="Доступные модули (тариф)")
    tariff_plan = models.CharField(max_length=50, default="full", blank=True, verbose_name="Тарифный план")
    updated_at = models.DateTimeField(auto_now=True)

    # All available modules (key → label) used for the sidebar / tariff toggles
    ALL_MODULES = [
        ("calendar", "Расписание"),
        ("appointments", "Записи"),
        ("patients", "Пациенты"),
        ("treatments", "Лечения"),
        ("services", "Услуги"),
        ("finance", "Финансы"),
        ("warehouse", "Склад"),
        ("medicines", "Лекарства"),
        ("technicians", "Техники"),
        ("tasks", "Задачи"),
        ("reports", "Аналитика"),
        ("staff", "Сотрудники"),
    ]

    TARIFF_CHOICES = [
        ("basic", "Базовый"),
        ("standard", "Стандарт"),
        ("premium", "Премиум"),
    ]
    TARIFF_PRESETS = {
        "basic": ["calendar", "appointments", "patients", "treatments", "services", "finance"],
        "standard": ["calendar", "appointments", "patients", "treatments", "services",
                     "finance", "warehouse", "medicines", "tasks", "staff"],
        "premium": [m[0] for m in ALL_MODULES],
    }

    def module_enabled(self, key):
        mods = self.enabled_modules or []
        return (not mods) or (key in mods)

    class Meta:
        verbose_name = "Настройки клиники"
        verbose_name_plural = "Настройки клиники"

    def __str__(self):
        return f"Настройки: {self.name}"

    @classmethod
    def get(cls):
        """Настройки ТЕКУЩЕЙ клиники (per-tenant). Создаются по требованию."""
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        if clinic is not None:
            obj, created = cls.objects.get_or_create(
                clinic=clinic, defaults={"name": clinic.name}
            )
            return obj
        # без выбранной клиники (суперадмин без выбора / сидинг) — служебная запись
        obj = cls.objects.filter(clinic__isnull=True).order_by("pk").first()
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1, defaults={"name": "SADAF"})
        return obj
