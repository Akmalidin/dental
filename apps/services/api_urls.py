from django.urls import path
from rest_framework import generics
from .models import Service, ServiceCategory
from .serializers import ServiceSerializer, ServiceCategorySerializer


class ServiceListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ServiceSerializer

    def get_queryset(self):
        qs = Service.objects.select_related("category")
        if self.request.query_params.get("active_only"):
            qs = qs.filter(is_active=True)
        return qs


class ServiceDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ServiceSerializer
    queryset = Service.objects.select_related("category")


class ServiceCategoryListAPIView(generics.ListCreateAPIView):
    serializer_class = ServiceCategorySerializer
    queryset = ServiceCategory.objects.all()


urlpatterns = [
    path("", ServiceListCreateAPIView.as_view(), name="api_services"),
    path("all/", ServiceListCreateAPIView.as_view(), name="api_services_all"),
    path("<int:pk>/", ServiceDetailAPIView.as_view(), name="api_service_detail"),
    path("categories/", ServiceCategoryListAPIView.as_view(), name="api_service_categories"),
]
