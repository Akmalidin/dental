from django.urls import path
from . import views

urlpatterns = [
    path("", views.finance_dashboard, name="finance_dashboard"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/create/", views.payment_create, name="payment_create"),
    path("payments/<int:pk>/edit/", views.payment_edit, name="payment_edit"),
    path("payments/<int:pk>/receipt/", views.payment_receipt, name="payment_receipt"),
    path("expenses/", views.expense_list, name="expense_list"),
    path("expenses/create/", views.expense_create, name="expense_create"),
    path("debtors/", views.debtors_list, name="debtors_list"),
]
