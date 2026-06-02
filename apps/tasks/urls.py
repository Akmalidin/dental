from django.urls import path
from . import views

urlpatterns = [
    path("", views.task_list, name="task_list"),
    path("create/", views.task_create, name="task_create"),
    path("<int:pk>/edit/", views.task_edit, name="task_edit"),
    path("<int:pk>/done/", views.task_done, name="task_done"),
]
