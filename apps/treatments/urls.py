from django.urls import path
from . import views
from . import views_visit

urlpatterns = [
    path("", views.treatment_list, name="treatment_list"),
    path("create/", views.treatment_create, name="treatment_create"),
    # Мастер приёма (6 шагов): Пациент → Жалобы → Осмотр → Диагноз → План → Итог
    path("visit/start/", views_visit.visit_start, name="visit_start"),
    path("visit/<int:pk>/", views_visit.visit_wizard, name="visit_wizard"),
    path("visit/<int:pk>/save/", views_visit.visit_save, name="visit_save"),
    path("visit/<int:pk>/upload/", views_visit.visit_file_upload, name="visit_file_upload"),
    path("visit/<int:pk>/commit/", views_visit.visit_commit, name="visit_commit"),
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
    path("<int:pk>/notify-wa/", views.treatment_notify_wa, name="treatment_notify_wa"),
    path("<int:pk>/status/", views.treatment_status, name="treatment_status"),
    path("<int:pk>/set-discount/", views.treatment_set_discount, name="treatment_set_discount"),
    path("<int:pk>/files/upload/", views.treatment_file_upload, name="treatment_file_upload"),
    path("<int:pk>/files/<int:file_pk>/delete/", views.treatment_file_delete, name="treatment_file_delete"),
    path("<int:pk>/emr/save/", views.treatment_emr_save, name="treatment_emr_save"),
    path("<int:pk>/emr/print/", views.treatment_emr_print, name="treatment_emr_print"),
    path("<int:pk>/receipt/", views.treatment_print, name="treatment_receipt"),
    path("<int:pk>/print/", views.treatment_print, name="treatment_print"),
    path("<int:pk>/receipt-print/", views.treatment_receipt_html, name="treatment_receipt_html"),
]
