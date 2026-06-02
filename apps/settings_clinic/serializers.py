from rest_framework import serializers
from .models import ClinicSettings


class ClinicSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicSettings
        fields = ["id", "logo", "name", "phone", "address", "working_hours",
                  "appointment_slot", "currency", "language", "require_unique_phone"]
