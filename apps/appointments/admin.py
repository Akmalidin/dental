from django.contrib import admin
from .models import Appointment, Cabinet, CancellationReason


@admin.register(CancellationReason)
class CancellationReasonAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "sort_order"]
    list_editable = ["is_active", "sort_order"]


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ["patient", "doctor", "start_at", "end_at", "status", "branch"]
    list_filter = ["status", "branch", "source"]
    search_fields = ["patient__first_name", "patient__last_name", "doctor__name"]
    date_hierarchy = "start_at"


@admin.register(Cabinet)
class CabinetAdmin(admin.ModelAdmin):
    list_display = ["name", "branch", "color", "is_active"]
