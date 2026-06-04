from django.urls import path
from . import views

urlpatterns = [
    path("", views.notification_list, name="notification_list"),
    path("poll/", views.notification_poll, name="notification_poll"),
    path("push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("<int:pk>/open/", views.notification_open, name="notification_open"),
    path("<int:pk>/read/", views.mark_read, name="notification_mark_read"),
    path("read-all/", views.mark_all_read, name="notification_mark_all_read"),
]
