from rest_framework import serializers
from .models import Treatment, TreatmentCure, TreatmentFile, TreatmentFollowUp


class TreatmentCureSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = TreatmentCure
        fields = [
            "id", "service", "service_name", "tooth_number",
            "quantity", "price", "subtotal", "doctor", "technician",
        ]


class TreatmentFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = TreatmentFile
        fields = ["id", "file", "name", "uploaded_by", "uploaded_at"]
        read_only_fields = ["uploaded_by", "uploaded_at"]


class TreatmentFollowUpSerializer(serializers.ModelSerializer):
    class Meta:
        model = TreatmentFollowUp
        fields = ["id", "scheduled_at", "status", "notes", "created_at"]
        read_only_fields = ["created_at"]


class TreatmentListSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)
    debt = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Treatment
        fields = [
            "id", "patient", "patient_name", "doctor", "doctor_name",
            "branch", "status", "total_amount", "discount", "paid_amount",
            "final_amount", "debt", "created_at",
        ]


class TreatmentDetailSerializer(serializers.ModelSerializer):
    cures = TreatmentCureSerializer(many=True, read_only=True)
    files = TreatmentFileSerializer(many=True, read_only=True)
    followups = TreatmentFollowUpSerializer(many=True, read_only=True)
    debt = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)

    class Meta:
        model = Treatment
        fields = [
            "id", "patient", "patient_name", "doctor", "doctor_name",
            "branch", "status", "total_amount", "discount", "paid_amount",
            "final_amount", "debt", "notes",
            "cures", "files", "followups", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "total_amount"]
