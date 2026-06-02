from django.urls import path
from rest_framework import generics, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Task
from .serializers import TaskSerializer


class TaskListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = TaskSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["status", "priority"]
    ordering = ["-created_at"]

    def get_queryset(self):
        from django.db.models import Q
        user = self.request.user
        qs = Task.objects.prefetch_related("assigned_to").select_related("created_by")
        if not user.is_superadmin and not user.is_admin:
            qs = qs.filter(Q(assigned_to=user) | Q(created_by=user))
        return qs


class TaskDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TaskSerializer
    queryset = Task.objects.prefetch_related("assigned_to")


urlpatterns = [
    path("", TaskListCreateAPIView.as_view(), name="api_tasks"),
    path("<int:pk>/", TaskDetailAPIView.as_view(), name="api_task_detail"),
]
