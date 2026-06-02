"""DRF API v1 URL configuration."""
from django.urls import path, include

urlpatterns = [
    path("auth/", include("apps.users.api_urls")),
    path("patients/", include("apps.patients.api_urls")),
    path("treatments/", include("apps.treatments.api_urls")),
    path("appointments/", include("apps.appointments.api_urls")),
    path("services/", include("apps.services.api_urls")),
    path("finance/", include("apps.finance.api_urls")),
    path("warehouse/", include("apps.warehouse.api_urls")),
    path("medicines/", include("apps.medicines.api_urls")),
    path("tasks/", include("apps.tasks.api_urls")),
    path("technicians/", include("apps.technicians.api_urls")),
    path("reports/", include("apps.reports.api_urls")),
    path("notifications/", include("apps.notifications.api_urls")),
    path("settings/", include("apps.settings_clinic.api_urls")),
]
