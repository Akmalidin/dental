from django.urls import path
from . import views

urlpatterns = [
    path("", views.service_list, name="service_list"),
    path("export/", views.service_export, name="service_export"),
    path("import/", views.service_import, name="service_import"),
    path("create/", views.service_create, name="service_create"),
    path("category/create/", views.category_create, name="category_create"),
    path("<int:pk>/edit/", views.service_edit, name="service_edit"),
    path("<int:pk>/delete/", views.service_delete, name="service_delete"),
]
