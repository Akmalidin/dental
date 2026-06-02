from django.contrib import admin
from .models import Medicine, PatientMedicine


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ["name", "form", "quantity", "unit", "min_qty", "is_active"]
    list_filter = ["form", "is_active"]
    search_fields = ["name"]


@admin.register(PatientMedicine)
class PatientMedicineAdmin(admin.ModelAdmin):
    list_display = ["patient", "medicine", "dosage", "doctor", "date"]
    list_filter = ["doctor"]
    date_hierarchy = "date"
