from django.urls import path
from . import views

urlpatterns = [
    path("", views.technician_list, name="technician_list"),
    path("create/", views.technician_create, name="technician_create"),
    path("tasks/", views.technician_tasks, name="technician_tasks"),
    path("payouts/", views.technician_payouts, name="technician_payouts"),
    path("<int:pk>/", views.technician_detail, name="technician_detail"),
    path("<int:pk>/pay/", views.technician_pay, name="technician_pay"),
    path("<int:pk>/warranty-case/", views.warranty_case_add, name="warranty_case_add"),
    path("orders/<int:pk>/status/", views.order_status, name="order_status"),
]
