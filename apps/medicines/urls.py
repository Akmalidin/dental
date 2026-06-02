from django.urls import path
from . import views

urlpatterns = [
    path("", views.medicine_list, name="medicine_list"),
    path("create/", views.medicine_create, name="medicine_create"),
    path("prescriptions/create/", views.prescription_create, name="prescription_create"),
]
