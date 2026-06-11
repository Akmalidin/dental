from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/daily-report/", views.profile_send_daily_report, name="profile_daily_report"),
    path("google/calendar/connect/", views.google_calendar_connect, name="google_calendar_connect"),
    path("google/calendar/callback/", views.google_calendar_callback, name="google_calendar_callback"),
    path("google/calendar/disconnect/", views.google_calendar_disconnect, name="google_calendar_disconnect"),
]
