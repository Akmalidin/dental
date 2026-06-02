from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Q

from .models import Patient, Tag, LeadSource
from .forms import PatientForm
from apps.treatments.models import Treatment
from apps.finance.models import Payment


@login_required
def patient_list(request):
    from datetime import date, timedelta
    from django.db.models import Sum
    from decimal import Decimal

    qs = Patient.objects.select_related("branch", "source").prefetch_related("tags")
    q = request.GET.get("q", "")
    branch_id = request.GET.get("branch", "")
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(middle_name__icontains=q)
            | Q(phone__icontains=q)
        )
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    today = date.today()
    week_ago = today - timedelta(days=7)

    # Stats
    all_count = Patient.objects.count()
    new_count = Patient.objects.filter(created_at__date__gte=week_ago).count()

    # Birthday in next 7 days
    birthday_count = 0
    for p in Patient.objects.exclude(birth_date=None).values_list("birth_date", flat=True):
        try:
            bd = p.replace(year=today.year)
        except ValueError:
            bd = p.replace(year=today.year, day=28)
        if today <= bd <= today + timedelta(days=7):
            birthday_count += 1

    debtors = Patient.objects.filter(balance__lt=0)
    debtors_count = debtors.count()
    debtors_total = debtors.aggregate(s=Sum("balance"))["s"] or Decimal(0)

    from apps.users.models import Branch
    branches = Branch.objects.all()

    return render(request, "patients/list.html", {
        "patients": qs,
        "q": q,
        "sources": LeadSource.objects.filter(is_active=True),
        "branches": branches,
        "all_count": all_count,
        "new_count": new_count,
        "birthday_count": birthday_count,
        "debtors_count": debtors_count,
        "debtors_total": abs(debtors_total),
    })


@login_required
def patient_create(request):
    form = PatientForm(request.POST or None)
    if form.is_valid():
        patient = form.save(commit=False)
        patient.created_by = request.user
        patient.save()
        form.save_m2m()
        messages.success(request, _("Пациент добавлен"))
        return redirect("patient_detail", pk=patient.pk)
    return render(request, "patients/form.html", {"form": form, "title": _("Новый пациент")})


@login_required
def patient_detail(request, pk):
    patient = get_object_or_404(Patient.objects.prefetch_related("tags"), pk=pk)
    treatments = Treatment.objects.filter(patient=patient).select_related(
        "doctor", "branch"
    ).prefetch_related(
        "cures__service", "cures__doctor", "files"
    ).order_by("-created_at")
    payments = Payment.objects.filter(patient=patient).select_related("received_by").order_by("-created_at")
    from apps.services.models import Service, ServiceCategory
    from apps.users.models import User as StaffUser
    _svcs = Service.objects.filter(is_active=True).select_related("category").order_by("category__sort_order","name").values(
        "id", "name", "price", "category__name", "category__id"
    )
    all_services_json = [
        {"id": s["id"], "name": s["name"], "price": float(s["price"]),
         "category__name": s["category__name"] or "", "category__id": s["category__id"] or 0}
        for s in _svcs
    ]
    service_categories_json = list(ServiceCategory.objects.values("id", "name"))
    doctors = StaffUser.objects.filter(role__name="doctor", is_active=True)
    treatment_plans = patient.treatment_plans.select_related("doctor").prefetch_related(
        "items__service", "items__doctor"
    ).order_by("-created_at")
    from apps.settings_clinic.models_documents import DocumentTemplate
    doc_templates = DocumentTemplate.objects.filter(is_active=True)
    return render(request, "patients/detail.html", {
        "doc_templates": doc_templates,
        "patient": patient,
        "treatments": treatments,
        "payments": payments,
        "treatment_plans": treatment_plans,
        "all_services_json": all_services_json,
        "service_categories_json": service_categories_json,
        "service_categories": ServiceCategory.objects.order_by("name"),
        "doctors": doctors,
    })


@login_required
def patient_edit(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    form = PatientForm(request.POST or None, instance=patient)
    if form.is_valid():
        form.save()
        messages.success(request, _("Данные обновлены"))
        return redirect("patient_detail", pk=patient.pk)
    return render(request, "patients/form.html", {"form": form, "title": _("Редактировать пациента"), "object": patient})


@login_required
def patient_delete(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == "POST":
        patient.delete()
        messages.success(request, _("Пациент удалён"))
        return redirect("patient_list")
    return render(request, "patients/confirm_delete.html", {"object": patient})
