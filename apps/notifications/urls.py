from django.urls import path
from . import views

urlpatterns = [
    path("", views.notification_list, name="notification_list"),
    path("poll/", views.notification_poll, name="notification_poll"),
    path("push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("<int:pk>/open/", views.notification_open, name="notification_open"),
    path("<int:pk>/read/", views.mark_read, name="notification_mark_read"),
    path("read-all/", views.mark_all_read, name="notification_mark_all_read"),
    path("templates/", views.message_templates, name="message_templates"),
    path("templates/<int:pk>/delete/", views.message_template_delete, name="message_template_delete"),
    path("wa-webhook/", views.wa_webhook, name="wa_webhook"),
    path("wa-inbox/", views.wa_inbox, name="wa_inbox"),
    path("wa-broadcast/", views.wa_broadcast, name="wa_broadcast"),
    path("wa-settings/", views.wa_settings, name="wa_settings"),
    path("wa-groups/", views.wa_groups, name="wa_groups"),
    path("wa-connect/", views.wa_connect, name="wa_connect"),
    path("tg-webhook/<slug:clinic_slug>/", views.tg_webhook, name="tg_webhook"),
    path("tg-inbox/", views.tg_inbox, name="tg_inbox"),
    path("tg-broadcast/", views.tg_broadcast, name="tg_broadcast"),
    path("tg-connect/", views.tg_connect, name="tg_connect"),
]
