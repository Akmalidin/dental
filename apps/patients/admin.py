from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Patient, Tag, LeadSource
from .models_insurance import InsuranceCompany


@admin.register(InsuranceCompany)
class InsuranceCompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "short_name", "phone", "is_active"]
    search_fields = ["name", "short_name"]


@admin.register(Patient)
class PatientAdmin(SimpleHistoryAdmin):
    list_display = ["full_name", "phone", "branch", "balance", "created_at"]
    list_filter = ["branch", "gender", "source"]
    search_fields = ["first_name", "last_name", "phone"]
    filter_horizontal = ["tags"]
    readonly_fields = ["created_at", "updated_at", "created_by"]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "color"]


@admin.register(LeadSource)
class LeadSourceAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]
