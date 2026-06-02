from django.urls import path
from rest_framework import generics
from .models import Product, ProductCategory, WarehouseEntry, WarehouseDistribution, Supplier
from .serializers import (
    ProductSerializer, ProductCategorySerializer,
    WarehouseEntrySerializer, WarehouseDistributionSerializer, SupplierSerializer,
)


class ProductListAPIView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    queryset = Product.objects.select_related("category", "supplier")


class WarehouseEntryListAPIView(generics.ListCreateAPIView):
    serializer_class = WarehouseEntrySerializer
    queryset = WarehouseEntry.objects.select_related("product", "supplier").order_by("-date")


class WarehouseDistributionListAPIView(generics.ListCreateAPIView):
    serializer_class = WarehouseDistributionSerializer
    queryset = WarehouseDistribution.objects.select_related("product", "branch").order_by("-date")


class SupplierListAPIView(generics.ListCreateAPIView):
    serializer_class = SupplierSerializer
    queryset = Supplier.objects.filter(is_active=True)


urlpatterns = [
    path("products/", ProductListAPIView.as_view(), name="api_products"),
    path("entries/", WarehouseEntryListAPIView.as_view(), name="api_warehouse_entries"),
    path("distributions/", WarehouseDistributionListAPIView.as_view(), name="api_warehouse_distributions"),
    path("suppliers/", SupplierListAPIView.as_view(), name="api_suppliers"),
]
