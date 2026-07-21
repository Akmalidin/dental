"""URLconf лендинга продукта (апекс/www.stom.asia) — см. apps/tenancy.py StomAsiaRoutingMiddleware.

Поддомены клиник (<slug>.stom.asia) НЕ используют этот urlconf — там открывается
обычная CRM (config.urls_dev / config.urls), см. StomAsiaRoutingMiddleware."""
from django.urls import path
from apps.marketing import views

urlpatterns = [
    path("", views.landing, name="marketing_landing"),
    path("lead/", views.landing_lead, name="marketing_lead"),
]
