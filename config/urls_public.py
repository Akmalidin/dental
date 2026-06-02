"""URL conf for the public schema (superadmin / central panel)."""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("central/", include("central.urls")),
    path("api/v1/central/", include("central.api_urls")),
]
