from django.urls import path
from . import views

urlpatterns = [
    path("", views.report_dashboard, name="report_dashboard"),
    path("treatments/", views.report_treatments, name="report_treatments"),
    path("doctors/", views.report_doctors, name="report_doctors"),
    path("finance/", views.report_finance, name="report_finance"),
    path("export/<str:report_type>/", views.export_excel, name="report_export"),
]
