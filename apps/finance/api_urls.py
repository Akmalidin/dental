from django.urls import path
from . import api_views

urlpatterns = [
    path("payments/", api_views.PaymentListCreateAPIView.as_view(), name="api_payments"),
    path("expenses/", api_views.ExpenseListCreateAPIView.as_view(), name="api_expenses"),
    path("expense-categories/", api_views.ExpenseCategoryListAPIView.as_view(), name="api_expense_categories"),
    path("summary/", api_views.finance_summary, name="api_finance_summary"),
    path("debtors/", api_views.debtors, name="api_debtors"),
]
