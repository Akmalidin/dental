from rest_framework import serializers
from .models import Product, ProductCategory, WarehouseEntry, WarehouseDistribution, Supplier


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "phone", "address", "is_active"]


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name"]


class ProductSerializer(serializers.ModelSerializer):
    is_low_stock = serializers.BooleanField(read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default="")

    class Meta:
        model = Product
        fields = ["id", "name", "category", "category_name", "unit", "quantity", "min_qty", "supplier", "is_active", "is_low_stock"]


class WarehouseEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WarehouseEntry
        fields = ["id", "product", "quantity", "price", "supplier", "date", "notes", "created_by", "created_at"]
        read_only_fields = ["created_by", "created_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class WarehouseDistributionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarehouseDistribution
        fields = ["id", "product", "quantity", "branch", "issued_to", "date", "notes", "created_at"]
        read_only_fields = ["created_at"]
