from django.urls import path
from . import views

urlpatterns = [
    path("export/", views.sync_export, name="sync_export"),
    path("push/", views.sync_push, name="sync_push"),
    path("run/", views.sync_run, name="sync_run"),
]
