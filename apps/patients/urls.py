from django.urls import path
from . import views

urlpatterns = [
    path("", views.patient_list, name="patient_list"),
    path("create/", views.patient_create, name="patient_create"),
    path("<int:pk>/", views.patient_detail, name="patient_detail"),
    path("<int:pk>/tooth-set/", views.patient_tooth_set, name="patient_tooth_set"),
    path("<int:pk>/edit/", views.patient_edit, name="patient_edit"),
    path("<int:pk>/delete/", views.patient_delete, name="patient_delete"),
]
