from rest_framework import serializers
from .models import Technician, TechnicianAgreement, TechnicianTask


class TechnicianAgreementSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)

    class Meta:
        model = TechnicianAgreement
        fields = ["id", "service", "service_name", "price"]


class TechnicianSerializer(serializers.ModelSerializer):
    agreements = TechnicianAgreementSerializer(many=True, read_only=True)

    class Meta:
        model = Technician
        fields = ["id", "name", "phone", "balance", "is_active", "notes", "agreements"]


class TechnicianTaskSerializer(serializers.ModelSerializer):
    technician_name = serializers.CharField(source="technician.name", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)

    class Meta:
        model = TechnicianTask
        fields = [
            "id", "technician", "technician_name", "treatment", "service", "service_name",
            "status", "amount", "deadline", "notes", "created_at",
        ]
