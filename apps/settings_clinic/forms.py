from django import forms
from .models import ClinicSettings


class ClinicSettingsForm(forms.ModelForm):
    class Meta:
        model = ClinicSettings
        fields = [
            "logo", "name", "phone", "address",
            "appointment_slot", "currency", "language",
            "require_unique_phone", "telegram_bot_token",
            "visits_journal_staff", "receipt_format",
            "receipt_clinic_name", "receipt_legal_name", "receipt_inn", "receipt_address",
            "warranty_terms",
        ]
        widgets = {"warranty_terms": forms.Textarea(attrs={"rows": 3})}
