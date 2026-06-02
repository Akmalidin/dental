from django.contrib import admin
from .models import Technician, TechnicianAgreement, TechnicianTask


class TechnicianAgreementInline(admin.TabularInline):
    model = TechnicianAgreement
    extra = 1


@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "balance", "is_active"]
    inlines = [TechnicianAgreementInline]


@admin.register(TechnicianTask)
class TechnicianTaskAdmin(admin.ModelAdmin):
    list_display = ["technician", "service", "status", "amount", "deadline"]
    list_filter = ["status"]
