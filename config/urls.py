from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from apps.finance.views import payment_public

urlpatterns = [
    # Django admin (per-tenant)
    path("django-admin/", admin.site.urls),

    # Публичный чек по QR (без логина)
    path("r/<uuid:token>/", payment_public, name="payment_public"),

    # Auth
    path("", include("apps.users.urls")),

    # Main app modules
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

    # REST API v1
    path("api/v1/", include("config.api_urls")),

    # API docs (dev only – protected in production via middleware)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    # Rosetta translations
    path("rosetta/", include("rosetta.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
