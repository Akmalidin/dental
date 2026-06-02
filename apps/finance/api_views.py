from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from decimal import Decimal

from .models import Payment, Expense, ExpenseCategory
from .serializers import (
    PaymentSerializer, ExpenseSerializer, ExpenseCategorySerializer,
    FinanceSummarySerializer, DebtorSerializer,
)
from apps.patients.models import Patient


class PaymentListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = PaymentSerializer

    def get_queryset(self):
        qs = Payment.objects.select_related("patient", "received_by", "treatment")
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        branch = self.request.query_params.get("branch")
        if start:
            qs = qs.filter(created_at__date__gte=start)
        if end:
            qs = qs.filter(created_at__date__lte=end)
        if branch:
            qs = qs.filter(branch_id=branch)
        return qs


class ExpenseListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ExpenseSerializer

    def get_queryset(self):
        return Expense.objects.select_related("category", "branch", "created_by")


class ExpenseCategoryListAPIView(generics.ListCreateAPIView):
    serializer_class = ExpenseCategorySerializer
    queryset = ExpenseCategory.objects.all()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def finance_summary(request):
    period = request.query_params.get("period", "month")
    today = date.today()
    if period == "today":
        start = today
        end = today
    elif period == "week":
        start = today - timezone.timedelta(days=7)
        end = today
    else:
        start = today.replace(day=1)
        end = today

    income = Payment.objects.filter(
        created_at__date__range=[start, end], type="income"
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    refunds = Payment.objects.filter(
        created_at__date__range=[start, end], type="refund"
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    expenses = Expense.objects.filter(
        date__range=[start, end]
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)

    data = {
        "period": period,
        "income": income,
        "refunds": refunds,
        "expenses": expenses,
        "net": income - refunds - expenses,
    }
    return Response(FinanceSummarySerializer(data).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def debtors(request):
    patients = Patient.objects.filter(balance__lt=0).order_by("balance")[:20]
    data = [
        {
            "patient_id": p.pk,
            "patient_name": p.full_name,
            "phone": p.phone,
            "debt": abs(p.balance),
        }
        for p in patients
    ]
    return Response(DebtorSerializer(data, many=True).data)
