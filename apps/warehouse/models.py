from django.db import models
from django.conf import settings
from apps.users.models import Branch
from apps.tenancy import ClinicScopedModel


class Supplier(ClinicScopedModel):
    name = models.CharField(max_length=200, verbose_name="Поставщик")
    phone = models.CharField(max_length=30, verbose_name="Телефон")
    address = models.CharField(max_length=500, blank=True, verbose_name="Адрес")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Поставщик"
        verbose_name_plural = "Поставщики"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductCategory(ClinicScopedModel):
    name = models.CharField(max_length=150, verbose_name="Категория")

    class Meta:
        verbose_name = "Категория материала"
        verbose_name_plural = "Категории материалов"

    def __str__(self):
        return self.name


class Product(ClinicScopedModel):
    name = models.CharField(max_length=200, verbose_name="Материал / товар")
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Категория",
    )
    unit = models.CharField(max_length=30, verbose_name="Единица измерения")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Остаток")
    min_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Минимальный остаток")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="products", verbose_name="Поставщик"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Материал"
        verbose_name_plural = "Материалы"
        ordering = ["category", "name"]

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_qty


class WarehouseEntry(models.Model):
    """Incoming stock."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="entries", verbose_name="Материал")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Количество")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Цена за единицу")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True,
        related_name="entries", verbose_name="Поставщик"
    )
    date = models.DateField(verbose_name="Дата")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="warehouse_entries"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Поступление"
        verbose_name_plural = "Поступления"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.product} +{self.quantity} [{self.date}]"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            Product.objects.filter(pk=self.product_id).update(
                quantity=models.F("quantity") + self.quantity
            )


class WarehouseDistribution(models.Model):
    """Write-off / distribution of stock."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="distributions", verbose_name="Материал")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Количество")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="distributions", verbose_name="Филиал")
    issued_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="distributions",
        verbose_name="Кому выдано",
    )
    date = models.DateField(verbose_name="Дата")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Списание/выдача"
        verbose_name_plural = "Списания/выдачи"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.product} -{self.quantity} [{self.date}]"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            Product.objects.filter(pk=self.product_id).update(
                quantity=models.F("quantity") - self.quantity
            )


class WarehouseTransfer(models.Model):
    """Transfer of materials between branches/warehouses."""

    from_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="transfers_out", verbose_name="Откуда")
    to_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="transfers_in", verbose_name="Куда")
    date = models.DateField(verbose_name="Дата")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="warehouse_transfers")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Перемещение"
        verbose_name_plural = "Перемещения"
        ordering = ["-date"]

    def __str__(self):
        return f"Перемещение {self.from_branch} → {self.to_branch} [{self.date}]"


class WarehouseTransferItem(models.Model):
    transfer = models.ForeignKey(WarehouseTransfer, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="transfer_items", verbose_name="Материал")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Количество")

    class Meta:
        verbose_name = "Позиция перемещения"
        verbose_name_plural = "Позиции перемещения"

    def __str__(self):
        return f"{self.product} × {self.quantity}"


class InventoryDocument(models.Model):
    """Stock inventory / reconciliation."""

    STATUS_DRAFT = "draft"
    STATUS_POSTED = "posted"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_POSTED, "Проведена"),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="inventories", verbose_name="Филиал")
    date = models.DateField(verbose_name="Дата")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT, verbose_name="Статус")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inventories")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Инвентаризация"
        verbose_name_plural = "Инвентаризации"
        ordering = ["-date"]

    def __str__(self):
        return f"Инвентаризация {self.branch} [{self.date}]"

    def post(self):
        """Apply inventory adjustments to actual product quantities."""
        if self.status == self.STATUS_POSTED:
            return
        for item in self.items.all():
            Product.objects.filter(pk=item.product_id).update(quantity=item.actual_qty)
        self.status = self.STATUS_POSTED
        self.save(update_fields=["status"])


class InventoryItem(models.Model):
    document = models.ForeignKey(InventoryDocument, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="inventory_items", verbose_name="Материал")
    system_qty = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="По системе")
    actual_qty = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Фактически")

    class Meta:
        verbose_name = "Позиция инвентаризации"
        verbose_name_plural = "Позиции инвентаризации"

    def __str__(self):
        return f"{self.product}: сис={self.system_qty} факт={self.actual_qty}"

    @property
    def difference(self):
        return self.actual_qty - self.system_qty
