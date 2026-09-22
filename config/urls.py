from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from apps.finance.views import payment_public
from apps.treatments.views import treatment_public
from apps.notifications.views import service_worker, web_manifest

urlpatterns = [
    # Django admin (per-tenant)
    path("django-admin/", admin.site.urls),

    # Публичный чек по QR (без логина)
    path("r/<uuid:token>/", payment_public, name="payment_public"),
    path("t/<uuid:token>/", treatment_public, name="treatment_public"),

    # Auth
    path("", include("apps.users.urls")),

    # Новый интерфейс (в разработке) — разбит на отдельные страницы/URL
    path("new/", include("apps.users.newui_urls")),

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
    # Service Worker и манифест ОБЯЗАНЫ отдаваться из корня сайта (не из
    # /notifications/) — иначе scope регистрации ('/sw.js' по умолчанию
    # покрывает весь сайт, из подпути — только этот подпуть) не накроет
    # приложение целиком, и push вообще не заработает. Раньше эти два
    # маршрута существовали только в config/urls_dev.py (локальная
    # разработка) — в проде (config.urls, см. ROOT_URLCONF в
    # config/settings/base.py) их не было вовсе, поэтому
    # navigator.serviceWorker.register('/sw.js') на проде всегда получал
    # 404 и Web Push (фоновые пуши на телефон/закрытую вкладку) не
    # работал никогда, только фолбэк — desktop-уведомления, пока вкладка
    # реально открыта и её кто-то поллит.
    path("sw.js", service_worker, name="service_worker"),
    path("manifest.json", web_manifest, name="web_manifest"),

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
