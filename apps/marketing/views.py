from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import LandingLead


def landing(request):
    return render(request, "marketing/landing.html")


@require_POST
def landing_lead(request):
    clinic_name = (request.POST.get("clinic_name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    city = (request.POST.get("city") or "").strip()
    if not clinic_name or not phone:
        messages.error(request, "Укажите название клиники и телефон")
        return redirect("/#contact")
    LandingLead.objects.create(clinic_name=clinic_name, phone=phone, city=city)
    messages.success(request, "Заявка отправлена — свяжемся с вами в течение дня.")
    return redirect("/#contact")
