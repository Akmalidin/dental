from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Treatment, TreatmentCure, TreatmentFile, TreatmentFollowUp
from .models_plan import TreatmentPlan, TreatmentPlanItem
from .models_emr import MedicalRecordTemplate, MedicalRecord


@admin.register(MedicalRecordTemplate)
class MedicalRecordTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]
    search_fields = ["name"]


@admin.register(MedicalRecord)
class MedicalRecordAdmin(admin.ModelAdmin):
    list_display = ["treatment", "patient", "doctor", "updated_at"]


class TreatmentPlanItemInline(admin.TabularInline):
    model = TreatmentPlanItem
    extra = 1


@admin.register(TreatmentPlan)
class TreatmentPlanAdmin(admin.ModelAdmin):
    list_display = ["pk", "patient", "doctor", "title", "status", "completion_pct", "created_at"]
    list_filter = ["status"]
    inlines = [TreatmentPlanItemInline]


class TreatmentCureInline(admin.TabularInline):
    model = TreatmentCure
    extra = 1
    fields = ["service", "tooth_number", "quantity", "price", "doctor"]


class TreatmentFileInline(admin.TabularInline):
    model = TreatmentFile
    extra = 0


@admin.register(Treatment)
class TreatmentAdmin(SimpleHistoryAdmin):
    list_display = ["pk", "patient", "doctor", "status", "total_amount", "paid_amount", "debt", "created_at"]
    list_filter = ["status", "branch"]
    search_fields = ["patient__first_name", "patient__last_name", "doctor__name"]
    inlines = [TreatmentCureInline, TreatmentFileInline]
    readonly_fields = ["total_amount", "created_at", "updated_at"]
