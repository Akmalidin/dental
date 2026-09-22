"""URLconf лендинга продукта (апекс/www.stom.asia) — см. apps/tenancy.py StomAsiaRoutingMiddleware.

Поддомены клиник (<slug>.stom.asia) НЕ используют этот urlconf — там открывается
обычная CRM (config.urls_dev / config.urls), см. StomAsiaRoutingMiddleware."""
from django.urls import path
from apps.marketing import views

urlpatterns = [
    path("", views.landing, name="marketing_landing"),
    path("robots.txt", views.robots, name="marketing_robots"),
    path("sitemap.xml", views.sitemap, name="marketing_sitemap"),
    path("lead/", views.landing_lead, name="marketing_lead"),
    path("book/", views.directory, name="marketing_directory"),
    path("book/<slug:slug>/", views.book_clinic, name="marketing_book_clinic"),
    path("book/<slug:slug>/slots/", views.book_clinic_slots, name="marketing_book_clinic_slots"),
    path("book/<slug:slug>/submit/", views.book_clinic_submit, name="marketing_book_clinic_submit"),
]
