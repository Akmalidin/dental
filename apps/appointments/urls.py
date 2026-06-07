from django.urls import path
from . import views

urlpatterns = [
    path("", views.appointment_list, name="appointment_list"),
    path("day/", views.appointment_day_grid, name="appointment_day_grid"),
    path("schedule/print/", views.schedule_print, name="schedule_print"),
    path("create/", views.appointment_create, name="appointment_create"),
    path("create-quick/", views.appointment_create_quick, name="appointment_create_quick"),
    path("<int:pk>/edit/", views.appointment_edit, name="appointment_edit"),
    path("<int:pk>/status/", views.appointment_status, name="appointment_status"),
    path("<int:pk>/finish/", views.appointment_finish, name="appointment_finish"),
    path("<int:pk>/move/", views.appointment_move, name="appointment_move"),
    path("<int:pk>/delete/", views.appointment_delete, name="appointment_delete"),
    path("<int:pk>/trash/", views.appointment_trash, name="appointment_trash"),
    path("<int:pk>/detail/", views.appointment_detail_json, name="appointment_detail_json"),
]
