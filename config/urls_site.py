"""URLconf публичного сайта клиники (поддомен <slug>.denta.tw1.ru)."""
from django.urls import path
from apps.users import site_views

urlpatterns = [
    path("", site_views.public_home, name="public_home"),
    path("service/<int:pk>/", site_views.public_service, name="public_service"),
    path("book/", site_views.public_book, name="public_book"),
]
