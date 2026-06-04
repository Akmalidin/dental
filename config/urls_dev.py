"""URL config для локальной разработки (без мультитенантности)."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from apps.notifications.views import service_worker, web_manifest

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),  # язык переключатель

    # Auth
    path("", include("apps.users.urls")),

    # App modules
    path("patients/", include("apps.patients.urls")),
    path("treatments/", include("apps.treatments.urls")),
    path("appointments/", include("apps.appointments.urls")),
    path("calendar/", include("apps.appointments.calendar_urls")),
    path("finance/", include("apps.finance.urls")),
    path("warehouse/", include("apps.warehouse.urls")),
    path("medicines/", include("apps.medicines.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("technicians/", include("apps.technicians.urls")),
    path("services/", include("apps.services.urls")),
    path("users/", include("apps.users.staff_urls")),
    path("reports/", include("apps.reports.urls")),
    path("settings/", include("apps.settings_clinic.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("sw.js", service_worker, name="service_worker"),
    path("manifest.json", web_manifest, name="web_manifest"),
    path("sync/", include("apps.sync.urls")),

    # Центральная панель (работает локально без схем)
    path("central/", include("central.urls")),

    # REST API v1
    path("api/v1/auth/", include("apps.users.api_urls")),
    path("api/v1/patients/", include("apps.patients.api_urls")),
    path("api/v1/treatments/", include("apps.treatments.api_urls")),
    path("api/v1/appointments/", include("apps.appointments.api_urls")),
    path("api/v1/services/", include("apps.services.api_urls")),
    path("api/v1/finance/", include("apps.finance.api_urls")),
    path("api/v1/warehouse/", include("apps.warehouse.api_urls")),
    path("api/v1/medicines/", include("apps.medicines.api_urls")),
    path("api/v1/tasks/", include("apps.tasks.api_urls")),
    path("api/v1/technicians/", include("apps.technicians.api_urls")),
    path("api/v1/reports/", include("apps.reports.api_urls")),
    path("api/v1/notifications/", include("apps.notifications.api_urls")),
    path("api/v1/settings/", include("apps.settings_clinic.api_urls")),

    # API docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
