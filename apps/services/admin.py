from django.contrib import admin
from .models import Service, ServiceCategory, ServiceMaterialNorm


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "color", "sort_order"]
    ordering = ["sort_order"]


class ServiceMaterialNormInline(admin.TabularInline):
    model = ServiceMaterialNorm
    extra = 1


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "category", "price", "dms_price", "duration", "is_active"]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "code"]
    inlines = [ServiceMaterialNormInline]
