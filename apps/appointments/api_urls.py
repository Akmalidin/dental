from django.urls import path
from . import api_views

urlpatterns = [
    path("", api_views.AppointmentListCreateAPIView.as_view(), name="api_appointments"),
    path("<int:pk>/", api_views.AppointmentDetailAPIView.as_view(), name="api_appointment_detail"),
    path("calendar/", api_views.CalendarEventsAPIView.as_view(), name="api_calendar_events"),
    path("available-slots/", api_views.available_slots, name="api_available_slots"),
    path("cabinets/", api_views.CabinetListCreateAPIView.as_view(), name="api_cabinets"),
]
