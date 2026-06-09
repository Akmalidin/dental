from django.db import models
from apps.tenancy import ClinicScopedModel, ClinicSoftDeleteModel


class ServiceCategory(ClinicScopedModel):
    name = models.CharField(max_length=150, verbose_name="Категория")
    color = models.CharField(max_length=7, default="#6366F1", verbose_name="Цвет")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Категория услуги"
        verbose_name_plural = "Категории услуг"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Service(ClinicSoftDeleteModel):
    name = models.CharField(max_length=200, verbose_name="Услуга")
    code = models.CharField(max_length=50, blank=True, verbose_name="Код услуги")
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services",
        verbose_name="Категория",
    )
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Цена (сом)")
    dms_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Цена ДМС (сом)"
    )
    duration = models.PositiveIntegerField(default=30, verbose_name="Длительность (мин)")
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    description = models.TextField(blank=True, verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Услуга"
        verbose_name_plural = "Услуги"
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class ServiceMaterialNorm(models.Model):
    """Norma raskhoda materialov dlya uslugi (dlya avto-spisaniya so sklada)."""

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="material_norms")
    product = models.ForeignKey(
        "warehouse.Product", on_delete=models.PROTECT, related_name="service_norms", verbose_name="Материал"
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=3, verbose_name="Количество")

    class Meta:
        verbose_name = "Норматив расхода"
        verbose_name_plural = "Нормативы расхода"
        unique_together = [["service", "product"]]

    def __str__(self):
        return f"{self.service.name} → {self.product.name} × {self.quantity}"
