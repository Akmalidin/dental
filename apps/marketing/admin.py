from django.contrib import admin
from .models import LandingLead


@admin.register(LandingLead)
class LandingLeadAdmin(admin.ModelAdmin):
    list_display = ("clinic_name", "phone", "city", "created_at", "contacted")
    list_filter = ("contacted",)
    list_editable = ("contacted",)
    search_fields = ("clinic_name", "phone", "city")
    ordering = ("-created_at",)
