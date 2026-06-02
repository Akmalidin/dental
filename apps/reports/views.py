from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from apps.treatments.models import Treatment
from apps.finance.models import Payment, Expense
from apps.appointments.models import Appointment
from apps.patients.models import Patient
from apps.users.decorators import role_required


@login_required
@role_required("superadmin", "admin_main", "admin")
def report_dashboard(request):
    import json
    from django.contrib.auth import get_user_model
    from apps.services.models import Service
    from apps.treatments.models import TreatmentCure
    User = get_user_model()
    today = date.today()

    # Period filter
    period = request.GET.get("period", "month")
    if period == "week":
        start = today - timedelta(days=7)
    elif period == "year":
        start = today.replace(month=1, day=1)
    else:  # month
        start = today.replace(day=1)

    treatments = Treatment.objects.filter(
        created_at__date__gte=start
    ).select_related("patient", "doctor", "branch")
    total_amount = treatments.aggregate(s=Sum("total_amount"))["s"] or Decimal(0)
    total_paid = treatments.aggregate(s=Sum("paid_amount"))["s"] or Decimal(0)

    # ── Revenue by doctor ──
    doctors = User.objects.filter(role__name="doctor", is_active=True).annotate(
        treatments_count=Count("treatments", filter=Q(treatments__created_at__date__gte=start)),
        total_revenue=Sum("treatments__total_amount", filter=Q(treatments__created_at__date__gte=start)),
    )

    # ── Revenue by service ──
    service_revenue = list(
        TreatmentCure.objects.filter(treatment__created_at__date__gte=start)
        .values("service__name")
        .annotate(cnt=Count("id"), revenue=Sum("price"))
        .order_by("-revenue")[:15]
    )
    service_donut = [[s["service__name"], float(s["revenue"] or 0)] for s in service_revenue[:6]]

    # ── Visits by day (chart) ──
    visits_by_day = {}
    for t in treatments:
        d = t.created_at.date().isoformat()
        visits_by_day[d] = visits_by_day.get(d, 0) + 1
    visits_chart = sorted(visits_by_day.items())

    # ── Visits by hour ──
    visits_by_hour = [0] * 24
    for t in treatments:
        visits_by_hour[t.created_at.hour] += 1

    # ── Income / expenses ──
    income = Payment.objects.filter(created_at__date__gte=start, type="income").aggregate(s=Sum("amount"))["s"] or Decimal(0)
    refunds = Payment.objects.filter(created_at__date__gte=start, type="refund").aggregate(s=Sum("amount"))["s"] or Decimal(0)
    expenses_total = Expense.objects.filter(date__gte=start).aggregate(s=Sum("amount"))["s"] or Decimal(0)

    # ── Income by day (chart) ──
    income_by_day = {}
    for p in Payment.objects.filter(created_at__date__gte=start, type="income"):
        d = p.created_at.date().isoformat()
        income_by_day[d] = income_by_day.get(d, 0) + float(p.amount)
    income_chart = sorted(income_by_day.items())

    # ── Patients: gender/age ──
    all_patients = Patient.objects.all()
    male = all_patients.filter(gender="male").count()
    female = all_patients.filter(gender="female").count()
    age_groups = {"0-17": 0, "18-30": 0, "31-45": 0, "46-60": 0, "60+": 0}
    for p in all_patients:
        age = p.age
        if age is None:
            continue
        if age < 18: age_groups["0-17"] += 1
        elif age <= 30: age_groups["18-30"] += 1
        elif age <= 45: age_groups["31-45"] += 1
        elif age <= 60: age_groups["46-60"] += 1
        else: age_groups["60+"] += 1

    # ── New patients ──
    new_patients = all_patients.filter(created_at__date__gte=start).count()

    # ── Sources (ad channels) ──
    from apps.patients.models import LeadSource
    sources = (
        LeadSource.objects.annotate(cnt=Count("patients")).order_by("-cnt")
    )

    # ── Retention: patients with >1 treatment ──
    returning = (
        Patient.objects.annotate(tc=Count("treatments")).filter(tc__gte=2).count()
    )
    retention_pct = int(returning / all_patients.count() * 100) if all_patients.count() else 0

    return render(request, "reports/dashboard.html", {
        "period": period,
        "treatments": treatments,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "doctors": doctors,
        "service_revenue": service_revenue,
        "service_donut_json": service_donut,
        "income": income,
        "refunds": refunds,
        "expenses": expenses_total,
        "net": income - refunds - expenses_total,
        "visits_chart_json": visits_chart,
        "income_chart_json": income_chart,
        "visits_by_hour_json": visits_by_hour,
        "male": male, "female": female,
        "age_groups_json": age_groups,
        "new_patients": new_patients,
        "sources": sources,
        "returning": returning,
        "retention_pct": retention_pct,
        "total_patients": all_patients.count(),
    })


@login_required
@role_required("superadmin", "admin_main", "admin")
def report_treatments(request):
    today = date.today()
    month_start = today.replace(day=1)
    treatments = Treatment.objects.filter(
        created_at__date__gte=month_start
    ).select_related("patient", "doctor", "branch")
    total_amount = treatments.aggregate(s=Sum("total_amount"))["s"] or Decimal(0)
    total_paid = treatments.aggregate(s=Sum("paid_amount"))["s"] or Decimal(0)
    return render(request, "reports/treatments.html", {
        "treatments": treatments,
        "total_amount": total_amount,
        "total_paid": total_paid,
    })


@login_required
@role_required("superadmin", "admin_main", "admin")
def report_doctors(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    today = date.today()
    month_start = today.replace(day=1)
    doctors = User.objects.filter(
        role__name="doctor",
        is_active=True,
    ).annotate(
        treatments_count=Count(
            "treatments",
            filter=Q(treatments__created_at__date__gte=month_start),
        ),
        total_revenue=Sum(
            "treatments__total_amount",
            filter=Q(treatments__created_at__date__gte=month_start),
        ),
    )
    return render(request, "reports/doctors.html", {"doctors": doctors})


@login_required
@role_required("superadmin", "admin_main", "admin")
def report_finance(request):
    today = date.today()
    month_start = today.replace(day=1)
    income = Payment.objects.filter(
        created_at__date__gte=month_start, type="income"
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    refunds = Payment.objects.filter(
        created_at__date__gte=month_start, type="refund"
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    expenses = Expense.objects.filter(
        date__gte=month_start
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    return render(request, "reports/finance.html", {
        "income": income,
        "refunds": refunds,
        "expenses": expenses,
        "net": income - refunds - expenses,
    })


@login_required
@role_required("superadmin", "admin_main", "admin")
def export_excel(request, report_type):
    """Export any report as Excel."""
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError:
        return HttpResponse("openpyxl не установлен", status=500)

    wb = openpyxl.Workbook()
    ws = wb.active

    if report_type == "treatments":
        ws.title = "Приёмы"
        ws.append(["ID", "Пациент", "Врач", "Статус", "Сумма", "Оплачено", "Долг", "Дата"])
        for t in Treatment.objects.select_related("patient", "doctor").order_by("-created_at")[:500]:
            ws.append([t.pk, str(t.patient), str(t.doctor), t.status, t.total_amount, t.paid_amount, t.debt, t.created_at.date()])
    elif report_type == "finance":
        ws.title = "Финансы"
        ws.append(["ID", "Пациент", "Сумма", "Метод", "Тип", "Дата"])
        for p in Payment.objects.select_related("patient").order_by("-created_at")[:500]:
            ws.append([p.pk, str(p.patient), p.amount, p.method, p.type, p.created_at.date()])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{report_type}.xlsx"'
    wb.save(response)
    return response
