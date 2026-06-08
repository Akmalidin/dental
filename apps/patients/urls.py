from django.urls import path
from . import views

urlpatterns = [
    path("", views.patient_list, name="patient_list"),
    path("export/", views.patient_export, name="patient_export"),
    path("import/", views.patient_import, name="patient_import"),
    path("create/", views.patient_create, name="patient_create"),
    path("<int:pk>/", views.patient_detail, name="patient_detail"),
    path("<int:pk>/tooth-set/", views.patient_tooth_set, name="patient_tooth_set"),
    path("<int:pk>/edit/", views.patient_edit, name="patient_edit"),
    path("<int:pk>/delete/", views.patient_delete, name="patient_delete"),
    path("<int:pk>/notify/", views.patient_notify, name="patient_notify"),
    path("<int:pk>/wa-messages/", views.patient_wa_messages, name="patient_wa_messages"),
]
