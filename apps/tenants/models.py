from django.db import models

try:
    from django_tenants.models import TenantMixin, DomainMixin
    TENANTS_ENABLED = True
except ImportError:
    # django-tenants не установлен (SQLite / dev режим) — используем простые модели
    TENANTS_ENABLED = False

    class TenantMixin(models.Model):
        schema_name = models.CharField(max_length=63, unique=True, db_index=True)

        class Meta:
            abstract = True

    class DomainMixin(models.Model):
        class Meta:
            abstract = True


class Tenant(TenantMixin):
    """Represents a single dental clinic."""

    name = models.CharField(max_length=200, verbose_name="Название клиники")
    slug = models.SlugField(unique=True, verbose_name="Поддомен")
    owner_email = models.EmailField(verbose_name="Email владельца")
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    if TENANTS_ENABLED:
        auto_create_schema = True

    class Meta:
        verbose_name = "Клиника (тенант)"
        verbose_name_plural = "Клиники (тенанты)"

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    """Domain / subdomain mapping for each tenant."""

    domain = models.CharField(max_length=253, unique=True, db_index=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="domains")
    is_primary = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Домен"
        verbose_name_plural = "Домены"

    def __str__(self):
        return self.domain


class Subscription(models.Model):
    PLAN_CHOICES = [
        ("trial", "Пробный"),
        ("basic", "Базовый"),
        ("pro", "Pro"),
        ("enterprise", "Enterprise"),
    ]

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="subscription")
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default="trial")
    started_at = models.DateField()
    expired_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Подписка"
        verbose_name_plural = "Подписки"

    def __str__(self):
        return f"{self.tenant.name} — {self.get_plan_display()}"
