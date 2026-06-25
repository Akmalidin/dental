from django.urls import path
from . import views

urlpatterns = [
    path("", views.patient_list, name="patient_list"),
    path("export/", views.patient_export, name="patient_export"),
    path("import/", views.patient_import, name="patient_import"),
    path("create/", views.patient_create, name="patient_create"),
    path("journal/", views.visits_journal, name="visits_journal"),
    path("journal/<int:pk>/dates/", views.visits_journal_patient, name="visits_journal_patient"),
    path("blacklist/", views.blacklist_view, name="blacklist"),
    path("blacklist/check/", views.blacklist_check, name="blacklist_check"),
    path("<int:pk>/blacklist-toggle/", views.patient_blacklist_toggle, name="patient_blacklist_toggle"),
    path("<int:pk>/visits/", views.patient_visits, name="patient_visits"),
    path("<int:pk>/", views.patient_detail, name="patient_detail"),
    path("<int:pk>/tooth-set/", views.patient_tooth_set, name="patient_tooth_set"),
    path("<int:pk>/card043/print/", views.patient_card043_print, name="patient_card043_print"),
    path("<int:pk>/edit/", views.patient_edit, name="patient_edit"),
    path("<int:pk>/delete/", views.patient_delete, name="patient_delete"),
    path("<int:pk>/notify/", views.patient_notify, name="patient_notify"),
    path("<int:pk>/wa-messages/", views.patient_wa_messages, name="patient_wa_messages"),
]
