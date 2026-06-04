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
    from apps.users.models import User
    staff = User.objects.filter(is_active=True).order_by("name")
    return render(request, "tasks/list.html", {"tasks": qs, "staff": staff})


def _notify_assignees(task, actor):
    """Отправить уведомление каждому исполнителю задачи (кроме автора)."""
    try:
        from apps.notifications.models import Notification
        for u in task.assigned_to.all():
            if u.pk == getattr(actor, "pk", None):
                continue
            Notification.send(
                u, "Новая задача: " + task.title,
                task.description[:200] or "Вам назначена задача",
                type="task", link="/tasks/",
            )
    except Exception:
        pass


@login_required
def task_create(request):
    form = TaskForm(request.POST or None, user=request.user)
    if form.is_valid():
        task = form.save(commit=False)
        task.created_by = request.user
        if not task.status:
            task.status = Task.STATUS_PENDING
        task.save()
        form.save_m2m()
        _notify_assignees(task, request.user)
        messages.success(request, _("Задача создана"))
        return redirect("task_list")
    return render(request, "tasks/form.html", {"form": form})


@login_required
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = TaskForm(request.POST or None, instance=task, user=request.user)
    if form.is_valid():
        task = form.save()
        if not task.status:
            task.status = Task.STATUS_PENDING
            task.save(update_fields=["status"])
        _notify_assignees(task, request.user)
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
