from django.urls import path
from . import newui_views as v

urlpatterns = [
    path("", v.newui_dashboard, name="newui_dashboard"),
    path("funnel/", v.newui_funnel, name="newui_funnel"),
    path("marketing/", v.newui_marketing, name="newui_marketing"),
    path("patients/", v.newui_patients, name="newui_patients"),
    path("patients/<int:pk>/", v.newui_patientcard, name="newui_patientcard"),
    path("blacklist/", v.newui_blacklist, name="newui_blacklist"),
    path("visits/", v.newui_visits, name="newui_visits"),
    path("schedule/", v.newui_schedule, name="newui_schedule"),
    path("treatplans/", v.newui_treatplans, name="newui_treatplans"),
    path("staff/", v.newui_staff, name="newui_staff"),
    path("services/", v.newui_services, name="newui_services"),
    path("warehouse/", v.newui_warehouse, name="newui_warehouse"),
    path("lab/", v.newui_lab, name="newui_lab"),
    path("cashdesk/", v.newui_cashdesk, name="newui_cashdesk"),
    path("finance/", v.newui_finance, name="newui_finance"),
    path("accounting/", v.newui_accounting, name="newui_accounting"),
    path("reports/", v.newui_reports, name="newui_reports"),
    path("messages/", v.newui_messages, name="newui_messages"),
    path("audit/", v.newui_audit, name="newui_audit"),
    path("settings/", v.newui_settings, name="newui_settings"),
    path("visit/start/", v.newui_visit_start, name="newui_visit_start"),
    path("visitcard/<int:pk>/", v.newui_visitcard, name="newui_visitcard"),
    path("menu-prefs/save/", v.newui_menu_prefs_save, name="newui_menu_prefs_save"),
]
