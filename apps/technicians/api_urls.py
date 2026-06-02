from django.urls import path
from rest_framework import generics
from .models import Technician, TechnicianTask
from .serializers import TechnicianSerializer, TechnicianTaskSerializer


class TechnicianListAPIView(generics.ListCreateAPIView):
    serializer_class = TechnicianSerializer
    queryset = Technician.objects.prefetch_related("agreements__service").filter(is_active=True)


class TechnicianTaskListAPIView(generics.ListCreateAPIView):
    serializer_class = TechnicianTaskSerializer
    queryset = TechnicianTask.objects.select_related("technician", "service").order_by("-created_at")


urlpatterns = [
    path("", TechnicianListAPIView.as_view(), name="api_technicians"),
    path("tasks/", TechnicianTaskListAPIView.as_view(), name="api_technician_tasks"),
]
