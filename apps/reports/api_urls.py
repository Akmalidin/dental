from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from datetime import date
from decimal import Decimal


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def treatments_report(request):
    from apps.treatments.models import Treatment
    month_start = date.today().replace(day=1)
    qs = Treatment.objects.filter(created_at__date__gte=month_start)
    return Response({
        "total": qs.count(),
        "amount": qs.aggregate(s=Sum("total_amount"))["s"] or 0,
        "paid": qs.aggregate(s=Sum("paid_amount"))["s"] or 0,
        "by_status": list(qs.values("status").annotate(count=Count("id"))),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def doctors_report(request):
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic
    month_start = date.today().replace(day=1)
    doctors = clinic_doctors(get_current_clinic()).annotate(
        treatments_count=Count("treatments", filter=Q(treatments__created_at__date__gte=month_start)),
        revenue=Sum("treatments__total_amount", filter=Q(treatments__created_at__date__gte=month_start)),
    ).values("id", "name", "treatments_count", "revenue")
    return Response(list(doctors))


urlpatterns = [
    path("treatments/", treatments_report, name="api_report_treatments"),
    path("doctors/", doctors_report, name="api_report_doctors"),
]
