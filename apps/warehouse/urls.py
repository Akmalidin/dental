from django.urls import path
from . import views

urlpatterns = [
    path("", views.warehouse_dashboard, name="warehouse_dashboard"),
    path("entries/", views.entry_list, name="entry_list"),
    path("entries/create/", views.entry_create, name="entry_create"),
    path("distributions/", views.distribution_list, name="distribution_list"),
    path("distributions/create/", views.distribution_create, name="distribution_create"),
    path("transfers/", views.transfer_list, name="transfer_list"),
    path("transfers/create/", views.transfer_create, name="transfer_create"),
    path("inventories/", views.inventory_list, name="inventory_list"),
    path("inventories/create/", views.inventory_create, name="inventory_create"),
    path("inventories/<int:pk>/post/", views.inventory_post, name="inventory_post"),
]
