from django.urls import path
from . import views

urlpatterns = [
    path("", views.treatment_list, name="treatment_list"),
    path("create/", views.treatment_create, name="treatment_create"),
    path("create-quick/", views.treatment_create_quick, name="treatment_create_quick"),
    path("plans/create/", views.plan_create, name="plan_create"),
    path("plans/items/<int:pk>/toggle/", views.plan_item_toggle, name="plan_item_toggle"),
    path("plans/<int:pk>/delete/", views.plan_delete, name="plan_delete"),
    path("plans/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("plans/<int:pk>/stage/add/", views.plan_stage_add, name="plan_stage_add"),
    path("plans/stages/<int:pk>/edit/", views.plan_stage_edit, name="plan_stage_edit"),
    path("plans/stages/<int:pk>/delete/", views.plan_stage_delete, name="plan_stage_delete"),
    path("plans/items/add/", views.plan_item_add, name="plan_item_add"),
    path("plans/items/<int:pk>/delete/", views.plan_item_delete, name="plan_item_delete"),
    path("plans/items/<int:pk>/move/", views.plan_item_move, name="plan_item_move"),
    path("plans/<int:pk>/print/", views.plan_print, name="plan_print"),
    path("<int:pk>/", views.treatment_detail, name="treatment_detail"),
    path("<int:pk>/edit/", views.treatment_edit, name="treatment_edit"),
    path("<int:pk>/delete/", views.treatment_delete, name="treatment_delete"),
    path("<int:pk>/status/", views.treatment_status, name="treatment_status"),
    path("<int:pk>/files/upload/", views.treatment_file_upload, name="treatment_file_upload"),
    path("<int:pk>/files/<int:file_pk>/delete/", views.treatment_file_delete, name="treatment_file_delete"),
    path("<int:pk>/emr/save/", views.treatment_emr_save, name="treatment_emr_save"),
    path("<int:pk>/emr/print/", views.treatment_emr_print, name="treatment_emr_print"),
    path("<int:pk>/receipt/", views.treatment_print, name="treatment_receipt"),
    path("<int:pk>/print/", views.treatment_print, name="treatment_print"),
]
