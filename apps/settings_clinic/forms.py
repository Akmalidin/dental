from django import forms
from .models import ClinicSettings


class ClinicSettingsForm(forms.ModelForm):
    class Meta:
        model = ClinicSettings
        fields = [
            "logo", "name", "phone", "address",
            "appointment_slot", "currency", "language",
            "require_unique_phone", "telegram_bot_token",
        ]
