from rest_framework import serializers
from django.db.models import Sum
from decimal import Decimal
from .models import Payment, Expense, ExpenseCategory, PatientAdvance


class PaymentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    received_by_name = serializers.CharField(source="received_by.name", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "patient", "patient_name", "treatment",
            "amount", "method", "type", "branch",
            "received_by", "received_by_name",
            "created_at", "notes",
        ]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        validated_data.setdefault("received_by", self.context["request"].user)
        return super().create(validated_data)


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name"]


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.name", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id", "category", "category_name", "amount",
            "description", "branch", "created_by", "created_by_name",
            "date", "created_at",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class FinanceSummarySerializer(serializers.Serializer):
    period = serializers.CharField()
    income = serializers.DecimalField(max_digits=14, decimal_places=2)
    refunds = serializers.DecimalField(max_digits=14, decimal_places=2)
    expenses = serializers.DecimalField(max_digits=14, decimal_places=2)
    net = serializers.DecimalField(max_digits=14, decimal_places=2)


class DebtorSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    patient_name = serializers.CharField()
    phone = serializers.CharField()
    debt = serializers.DecimalField(max_digits=14, decimal_places=2)
