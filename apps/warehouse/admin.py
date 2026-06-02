from django.contrib import admin
from .models import (
    Product, ProductCategory, WarehouseEntry, WarehouseDistribution, Supplier,
    WarehouseTransfer, WarehouseTransferItem, InventoryDocument, InventoryItem,
)


class WarehouseTransferItemInline(admin.TabularInline):
    model = WarehouseTransferItem
    extra = 1


@admin.register(WarehouseTransfer)
class WarehouseTransferAdmin(admin.ModelAdmin):
    list_display = ["pk", "from_branch", "to_branch", "date", "created_by"]
    inlines = [WarehouseTransferItemInline]


class InventoryItemInline(admin.TabularInline):
    model = InventoryItem
    extra = 0


@admin.register(InventoryDocument)
class InventoryDocumentAdmin(admin.ModelAdmin):
    list_display = ["pk", "branch", "date", "status", "created_by"]
    list_filter = ["status", "branch"]
    inlines = [InventoryItemInline]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "quantity", "unit", "min_qty", "is_low_stock", "supplier"]
    list_filter = ["category", "is_active"]
    search_fields = ["name"]


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ["name"]


@admin.register(WarehouseEntry)
class WarehouseEntryAdmin(admin.ModelAdmin):
    list_display = ["product", "quantity", "price", "supplier", "date"]
    date_hierarchy = "date"


@admin.register(WarehouseDistribution)
class WarehouseDistributionAdmin(admin.ModelAdmin):
    list_display = ["product", "quantity", "branch", "date"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "is_active"]
