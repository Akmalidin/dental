from django.urls import path
from . import views

urlpatterns = [
    path("", views.central_dashboard, name="central_dashboard"),
    path("tenants/", views.tenant_list, name="central_tenant_list"),
    path("tenants/create/", views.tenant_create, name="central_tenant_create"),
    path("tenants/<int:pk>/block/", views.tenant_block, name="central_tenant_block"),
    path("tenants/<int:pk>/unblock/", views.tenant_unblock, name="central_tenant_unblock"),
    path("subscriptions/", views.subscription_list, name="central_subscription_list"),
]
