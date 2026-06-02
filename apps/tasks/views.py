from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from .models import Task
from .forms import TaskForm


@login_required
def task_list(request):
    qs = Task.objects.prefetch_related("assigned_to").select_related("created_by")
    if not request.user.is_superadmin and not request.user.is_admin:
        qs = qs.filter(Q(assigned_to=request.user) | Q(created_by=request.user))
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    return render(request, "tasks/list.html", {"tasks": qs})


@login_required
def task_create(request):
    form = TaskForm(request.POST or None, user=request.user)
    if form.is_valid():
        task = form.save(commit=False)
        task.created_by = request.user
        task.save()
        form.save_m2m()
        messages.success(request, _("Задача создана"))
        return redirect("task_list")
    return render(request, "tasks/form.html", {"form": form})


@login_required
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = TaskForm(request.POST or None, instance=task, user=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, _("Задача обновлена"))
        return redirect("task_list")
    return render(request, "tasks/form.html", {"form": form, "object": task})


@login_required
def task_done(request, pk):
    task = get_object_or_404(Task, pk=pk)
    task.status = Task.STATUS_DONE
    task.save()
    messages.success(request, _("Задача отмечена выполненной"))
    return redirect("task_list")
