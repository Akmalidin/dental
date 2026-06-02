from rest_framework import generics, filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from datetime import datetime, timedelta
from django.utils import timezone

from .models import Appointment, Cabinet
from .serializers import AppointmentSerializer, AppointmentCalendarSerializer, CabinetSerializer


class AppointmentListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = AppointmentSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["status", "doctor", "branch", "patient"]
    ordering = ["start_at"]

    def get_queryset(self):
        qs = Appointment.objects.select_related("patient", "doctor", "cabinet", "branch", "service")
        if self.request.user.is_doctor:
            qs = qs.filter(doctor=self.request.user)
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        if start:
            qs = qs.filter(start_at__gte=start)
        if end:
            qs = qs.filter(end_at__lte=end)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AppointmentDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AppointmentSerializer
    queryset = Appointment.objects.select_related("patient", "doctor", "cabinet", "branch", "service")


class CalendarEventsAPIView(generics.ListAPIView):
    """Returns FullCalendar-compatible event list (raw array, no pagination)."""

    serializer_class = AppointmentCalendarSerializer
    pagination_class = None  # FullCalendar needs a plain array, not paginated object

    def get_queryset(self):
        # Include cancelled appointments — they're shown dimmed on the calendar
        qs = Appointment.objects.select_related("patient", "doctor", "cancellation_reason")
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        doctor = self.request.query_params.get("doctor")
        if start:
            qs = qs.filter(start_at__gte=start)
        if end:
            qs = qs.filter(end_at__lte=end)
        if doctor:
            qs = qs.filter(doctor_id=doctor)
        if self.request.user.is_doctor:
            qs = qs.filter(doctor=self.request.user)
        return qs


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def available_slots(request):
    """Return available 30-min slots for a doctor on a given date."""
    doctor_id = request.query_params.get("doctor")
    date_str = request.query_params.get("date")
    if not doctor_id or not date_str:
        return Response({"error": "doctor and date are required"}, status=400)

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

    existing = Appointment.objects.filter(
        doctor_id=doctor_id,
        start_at__date=date,
    ).exclude(status="cancelled").values_list("start_at", "end_at")

    start_hour, end_hour = 9, 18
    slot_minutes = 30
    slots = []
    current = datetime.combine(date, datetime.min.time().replace(hour=start_hour))
    end_time = datetime.combine(date, datetime.min.time().replace(hour=end_hour))

    while current < end_time:
        slot_end = current + timedelta(minutes=slot_minutes)
        is_busy = any(
            not (slot_end <= s or current >= e)
            for s, e in ((s.replace(tzinfo=None), e.replace(tzinfo=None)) for s, e in existing)
        )
        if not is_busy:
            slots.append({
                "start": current.strftime("%Y-%m-%dT%H:%M"),
                "end": slot_end.strftime("%Y-%m-%dT%H:%M"),
            })
        current = slot_end

    return Response(slots)


class CabinetListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = CabinetSerializer
    queryset = Cabinet.objects.select_related("branch")
