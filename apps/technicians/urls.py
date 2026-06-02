from django.urls import path
from . import views

urlpatterns = [
    path("", views.technician_list, name="technician_list"),
    path("create/", views.technician_create, name="technician_create"),
    path("tasks/", views.technician_tasks, name="technician_tasks"),
]
