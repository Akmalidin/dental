from django.urls import path
from . import views

urlpatterns = [
    path("", views.settings_view, name="clinic_settings"),
    path("references/", views.references, name="references"),
    path("emr-templates/", views.emr_template_list, name="emr_template_list"),
    path("emr-templates/create/", views.emr_template_edit, name="emr_template_create"),
    path("emr-templates/<int:pk>/edit/", views.emr_template_edit, name="emr_template_edit"),
    path("emr-templates/<int:pk>/delete/", views.emr_template_delete, name="emr_template_delete"),
    path("tooth-statuses/", views.tooth_status_list, name="tooth_status_list"),
    path("tooth-statuses/<int:pk>/edit/", views.tooth_status_edit, name="tooth_status_edit"),
    path("tooth-statuses/<int:pk>/delete/", views.tooth_status_delete, name="tooth_status_delete"),
    path("references/<str:kind>/add/", views.reference_add, name="reference_add"),
    path("references/<str:kind>/<int:pk>/delete/", views.reference_delete, name="reference_delete"),
    path("documents/", views.document_list, name="document_list"),
    path("documents/create/", views.document_create, name="document_create"),
    path("documents/<int:pk>/edit/", views.document_edit, name="document_edit"),
    path("documents/<int:pk>/delete/", views.document_delete, name="document_delete"),
    path("documents/<int:pk>/render/<int:patient_pk>/", views.document_render, name="document_render"),
]
