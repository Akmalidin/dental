"""URL config для локальной разработки (без мультитенантности)."""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from apps.appointments.api_views import CalendarEventsAPIView
from apps.notifications.views import service_worker, web_manifest
from apps.finance.views import payment_public
from apps.treatments.views import treatment_public
from apps.users.media_views import protected_media


def _app_robots(request):
    """CRM (app.sadaf.kg) — приватный вход персонала, индексация не нужна."""
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain; charset=utf-8")


# Django-admin: свой вход отключён — неавторизованных уводим на общий /login/,
# где есть блокировка после неудачных попыток и бан по IP.
admin.site.login = login_required(admin.site.login)

urlpatterns = [
    # снимки/документы/вложения переписки — только после проверки входа и
    # клиники (на сервере nginx передаёт эти папки сюда, см. media_views)
    re_path(r"^media/(?P<path>(?:treatments|chat_media|tech_orders)/.+)$", protected_media, name="protected_media"),
    path("robots.txt", _app_robots, name="app_robots"),
    path("django-admin/", admin.site.urls),  # вход — только через общий /login/ (см. ниже)
    path("i18n/", include("django.conf.urls.i18n")),  # язык переключатель

    # Публичный чек по QR (без логина)
    path("r/<uuid:token>/", payment_public, name="payment_public"),
    path("t/<uuid:token>/", treatment_public, name="treatment_public"),

    # Auth
    path("", include("apps.users.urls")),

    # Новый интерфейс (в разработке) — разбит на отдельные страницы/URL
    path("new/", include("apps.users.newui_urls")),

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

    # REST API v1: остальные эндпоинты отключены (не использовались интерфейсом
    # и не были привязаны к клинике — см. аудит безопасности). Нужен только
    # календарь старого интерфейса.
    path("api/v1/appointments/calendar/", CalendarEventsAPIView.as_view(), name="api_calendar_events"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
