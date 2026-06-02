from rest_framework import serializers
from .models import Service, ServiceCategory


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "color", "sort_order"]


class ServiceSerializer(serializers.ModelSerializer):
    category = ServiceCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ServiceCategory.objects.all(), source="category", write_only=True, required=False
    )

    class Meta:
        model = Service
        fields = ["id", "name", "category", "category_id", "price", "duration", "is_active", "description"]
