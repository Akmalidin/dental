from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from .models import Technician, TechnicianTask
from .forms import TechnicianForm, TechnicianTaskForm


@login_required
def technician_list(request):
    technicians = Technician.objects.prefetch_related("agreements__service").filter(is_active=True)
    tech_tasks = TechnicianTask.objects.select_related("technician", "service").order_by("-created_at")[:50]
    return render(request, "technicians/list.html", {"technicians": technicians, "tech_tasks": tech_tasks})


@login_required
def technician_create(request):
    form = TechnicianForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, _("Техник добавлен"))
        return redirect("technician_list")
    return render(request, "technicians/form.html", {"form": form})


@login_required
def technician_tasks(request):
    tasks = TechnicianTask.objects.select_related("technician", "service", "treatment").order_by("-created_at")
    return render(request, "technicians/tasks.html", {"tasks": tasks})
