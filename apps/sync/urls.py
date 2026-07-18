from django.urls import path
from . import views

urlpatterns = [
    path("export/", views.sync_export, name="sync_export"),
    path("push/", views.sync_push, name="sync_push"),
    path("run/", views.sync_run, name="sync_run"),
    path("conflicts/", views.sync_conflicts, name="sync_conflicts"),
    path("conflicts/<int:pk>/resolve/", views.sync_conflict_resolve, name="sync_conflict_resolve"),
]
