from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from .models import Medicine, PatientMedicine
from .forms import MedicineForm, PatientMedicineForm


@login_required
def medicine_list(request):
    medicines = Medicine.objects.filter(is_active=True)
    prescriptions = PatientMedicine.objects.select_related(
        "patient", "medicine", "doctor"
    ).order_by("-date")[:50]
    if request.user.is_doctor:
        prescriptions = prescriptions.filter(doctor=request.user)
    return render(request, "medicines/list.html", {
        "medicines": medicines,
        "prescriptions": prescriptions,
    })


@login_required
def medicine_create(request):
    form = MedicineForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        med = form.save(commit=False)
        # Modal form has no is_active checkbox → ensure active on create
        if "is_active" not in request.POST:
            med.is_active = True
        med.save()
        messages.success(request, _("Лекарство добавлено"))
        return redirect("medicine_list")
    return render(request, "medicines/form.html", {"form": form})


@login_required
def prescription_create(request):
    form = PatientMedicineForm(request.POST or None, initial={"doctor": request.user})
    if form.is_valid():
        form.save()
        messages.success(request, _("Назначение создано"))
        return redirect("medicine_list")
    return render(request, "medicines/prescription_form.html", {"form": form})
