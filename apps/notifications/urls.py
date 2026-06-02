from django.urls import path
from . import views

urlpatterns = [
    path("", views.notification_list, name="notification_list"),
    path("<int:pk>/read/", views.mark_read, name="notification_mark_read"),
    path("read-all/", views.mark_all_read, name="notification_mark_all_read"),
]
