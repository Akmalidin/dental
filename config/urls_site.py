"""URLconf публичного сайта клиники (поддомен <slug>.denta.tw1.ru)."""
from django.urls import path
from apps.users import site_views

urlpatterns = [
    path("robots.txt", site_views.public_robots, name="public_robots"),
    path("sitemap.xml", site_views.public_sitemap, name="public_sitemap"),
    path("", site_views.public_home, name="public_home"),
    path("doctor/<int:pk>/", site_views.public_doctor, name="public_doctor"),
    path("service/<int:pk>/", site_views.public_service, name="public_service"),
    path("book/", site_views.public_book, name="public_book"),
    path("book/slots/", site_views.public_slots, name="public_slots"),
    path("book/submit/", site_views.public_book_submit, name="public_book_submit"),
]
