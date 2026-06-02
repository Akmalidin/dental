from django.contrib import admin
from .models import ClinicSettings
from .models_documents import DocumentTemplate


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "doc_type", "is_active", "updated_at"]
    list_filter = ["doc_type", "is_active"]
    search_fields = ["name"]


@admin.register(ClinicSettings)
class ClinicSettingsAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "language", "currency"]

    def has_add_permission(self, request):
        try:
            return not ClinicSettings.objects.exists()
        except Exception:
            return False
