from rest_framework import serializers
from .models import Medicine, PatientMedicine


class MedicineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Medicine
        fields = ["id", "name", "form", "quantity", "unit", "min_qty", "is_active"]


class PatientMedicineSerializer(serializers.ModelSerializer):
    medicine_name = serializers.CharField(source="medicine.name", read_only=True)
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)

    class Meta:
        model = PatientMedicine
        fields = [
            "id", "patient", "treatment", "medicine", "medicine_name",
            "dosage", "duration", "doctor", "doctor_name", "date", "notes",
        ]
        read_only_fields = ["id"]
