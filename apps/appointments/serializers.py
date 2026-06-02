from rest_framework import serializers
from .models import Appointment, Cabinet


class CabinetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cabinet
        fields = ["id", "name", "branch", "color", "is_active"]


class AppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True, default="")
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True, default="")
    duration_minutes = serializers.IntegerField(read_only=True)
    cabinet_name = serializers.CharField(source="cabinet.name", read_only=True, default="")

    class Meta:
        model = Appointment
        fields = [
            "id", "patient", "patient_name", "doctor", "doctor_name",
            "cabinet", "cabinet_name", "branch", "service", "service_name",
            "start_at", "end_at", "duration_minutes",
            "status", "notes", "source", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, data):
        if data.get("start_at") and data.get("end_at"):
            if data["start_at"] >= data["end_at"]:
                raise serializers.ValidationError("Время начала должно быть раньше времени конца")
        return data


class AppointmentCalendarSerializer(serializers.ModelSerializer):
    """Compact serializer for FullCalendar events."""

    title = serializers.SerializerMethodField()
    start = serializers.DateTimeField(source="start_at")
    end = serializers.DateTimeField(source="end_at")
    color = serializers.SerializerMethodField()
    className = serializers.SerializerMethodField()
    extendedProps = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = ["id", "title", "start", "end", "color", "className", "extendedProps"]

    def get_className(self, obj):
        return "appt-cancelled" if obj.status == "cancelled" else ""

    def get_title(self, obj):
        patient = obj.patient.full_name if obj.patient else "Без пациента"
        return f"{patient} — {obj.doctor.name}"

    def get_color(self, obj):
        colors = {
            "scheduled": "#6366F1",   # новые — индиго
            "confirmed": "#6366F1",
            "arrived": "#F59E0B",     # на приёме — оранжевый
            "in_progress": "#F59E0B",
            "completed": "#22C55E",   # завершён — зелёный
            "no_show": "#EF4444",
            "cancelled": "#EF4444",   # отменён — красный
        }
        return colors.get(obj.status, "#6366F1")

    def get_extendedProps(self, obj):
        return {
            "status": obj.status,
            "status_display": obj.get_status_display(),
            "patient_id": obj.patient_id,
            "doctor_id": obj.doctor_id,
            "notes": obj.notes,
            "cancel_reason": obj.cancellation_reason.name if obj.cancellation_reason else "",
            "cancel_note": obj.cancel_note,
        }
