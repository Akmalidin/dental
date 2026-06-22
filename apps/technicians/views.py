from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.db.models import Q, Sum

from .models import (Technician, TechnicianAgreement, TechnicianTask,
                     TechnicianOrderEvent, TechnicianWarrantyCase)
from .forms import TechnicianForm


@login_required
def technician_list(request):
    """Справочник техников + краткая сводка заказов."""
    technicians = Technician.objects.prefetch_related("agreements__service").all()
    if request.GET.get("only_active") != "0":
        technicians = technicians.filter(is_active=True)
    open_counts = {}
    for t in TechnicianTask.objects.filter(status__in=TechnicianTask.OPEN_STATUSES).values_list("technician_id", flat=True):
        open_counts[t] = open_counts.get(t, 0) + 1
    technicians = list(technicians)
    for tech in technicians:
        tech.open_orders = open_counts.get(tech.pk, 0)
    return render(request, "technicians/list.html", {
        "technicians": technicians,
        "form": TechnicianForm(),
    })


@login_required
def technician_create(request):
    form = TechnicianForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Техник добавлен"))
        return redirect("technician_list")
    return render(request, "technicians/form.html", {"form": form})


@login_required
def technician_detail(request, pk):
    tech = get_object_or_404(Technician, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "edit":
            form = TechnicianForm(request.POST, instance=tech)
            if form.is_valid():
                form.save()
                messages.success(request, _("Сохранено"))
            return redirect("technician_detail", pk=pk)
        if action == "add_price":
            from apps.services.models import Service
            svc = Service.objects.filter(pk=request.POST.get("service")).first()
            price = request.POST.get("price") or 0
            if svc:
                TechnicianAgreement.objects.update_or_create(
                    technician=tech, service=svc, defaults={"price": price})
                messages.success(request, _("Расценка сохранена"))
            return redirect("technician_detail", pk=pk)
        if action == "del_price":
            TechnicianAgreement.objects.filter(pk=request.POST.get("id"), technician=tech).delete()
            return redirect("technician_detail", pk=pk)

    orders = (TechnicianTask.objects.filter(technician=tech)
              .select_related("patient", "service", "treatment").order_by("-created_at"))
    payable = orders.filter(status=TechnicianTask.STATUS_INSTALLED, paid=False)
    payable_sum = payable.aggregate(s=Sum("amount"))["s"] or Decimal(0)
    from apps.services.models import Service
    return render(request, "technicians/detail.html", {
        "tech": tech, "form": TechnicianForm(instance=tech),
        "agreements": tech.agreements.select_related("service").all(),
        "orders": list(orders[:100]),
        "warranty_cases": tech.warranty_cases.select_related("patient", "task").all(),
        "payable_sum": payable_sum, "payable_count": payable.count(),
        "services": Service.objects.filter(is_active=True).order_by("name"),
    })


@login_required
def technician_tasks(request):
    """Все заказы техникам: таблица + фильтры + алерт просрочки."""
    qs = TechnicianTask.objects.select_related("technician", "service", "patient", "treatment").order_by("-created_at")
    f_tech = request.GET.get("tech", "")
    f_status = request.GET.get("status", "")
    f_q = (request.GET.get("q", "") or "").strip()
    if f_tech:
        qs = qs.filter(technician_id=f_tech)
    if f_status:
        qs = qs.filter(status=f_status)
    if f_q:
        qs = qs.filter(Q(patient__first_name__icontains=f_q) | Q(patient__last_name__icontains=f_q)
                       | Q(service__name__icontains=f_q) | Q(tooth_number__icontains=f_q))
    today = timezone.localdate()
    overdue = list(TechnicianTask.objects.select_related("technician", "patient", "service")
                   .filter(status__in=TechnicianTask.OPEN_STATUSES, expected_ready__lt=today))
    return render(request, "technicians/tasks.html", {
        "tasks": list(qs[:400]),
        "technicians": Technician.objects.filter(is_active=True),
        "statuses": TechnicianTask.STATUS_CHOICES,
        "f_tech": f_tech, "f_status": f_status, "f_q": f_q,
        "overdue": overdue, "overdue_count": len(overdue),
    })


@login_required
@require_POST
def order_status(request, pk):
    """Смена статуса заказа + журнал, ключевые даты, гарантия и запись в чек/карту."""
    task = get_object_or_404(TechnicianTask, pk=pk)
    new_status = request.POST.get("status")
    valid = dict(TechnicianTask.STATUS_CHOICES)
    if new_status not in valid:
        return redirect(request.META.get("HTTP_REFERER") or "technician_tasks")
    task.status = new_status
    today = timezone.localdate()
    if new_status == TechnicianTask.STATUS_READY and not task.ready_at:
        task.ready_at = today
    if new_status == TechnicianTask.STATUS_INSTALLED:
        if not task.installed_at:
            task.installed_at = today
        task.warranty_until = task.compute_warranty()
        if task.cure_id:
            from apps.treatments.models import TreatmentCure
            TreatmentCure.objects.filter(pk=task.cure_id).update(
                technician=task.technician, warranty_until=task.warranty_until, lab_order=task)
    task.save()
    TechnicianOrderEvent.objects.create(task=task, status=new_status, by=request.user)
    messages.success(request, _("Статус заказа: %(s)s") % {"s": valid[new_status]})
    return redirect(request.META.get("HTTP_REFERER") or "technician_tasks")


@login_required
def technician_payouts(request):
    """Расчёты с техниками: установленные неоплаченные заказы → выплата."""
    rows = []
    for tech in Technician.objects.all():
        payable = TechnicianTask.objects.filter(
            technician=tech, status=TechnicianTask.STATUS_INSTALLED, paid=False)
        s = payable.aggregate(x=Sum("amount"))["x"] or Decimal(0)
        cnt = payable.count()
        if cnt:
            rows.append({"tech": tech, "sum": s, "count": cnt})
    return render(request, "technicians/payouts.html", {"rows": rows})


@login_required
@require_POST
def technician_pay(request, pk):
    """Выплатить технику: создать расход «Оплата лаборатории» и пометить заказы оплаченными."""
    tech = get_object_or_404(Technician, pk=pk)
    payable = list(TechnicianTask.objects.filter(
        technician=tech, status=TechnicianTask.STATUS_INSTALLED, paid=False))
    if not payable:
        messages.info(request, _("Нет заказов к выплате"))
        return redirect("technician_payouts")
    total = sum((t.amount for t in payable), Decimal(0))
    from apps.finance.models import Expense, ExpenseCategory
    from apps.users.models import Branch
    cat, _x = ExpenseCategory.objects.get_or_create(name="Оплата лаборатории")
    branch = (Branch.objects.filter(is_main=True).first() or Branch.objects.first())
    exp = Expense.objects.create(
        category=cat, amount=total, branch=branch, created_by=request.user, date=timezone.localdate(),
        description=f"Оплата технику {tech.name} за {len(payable)} заказ(ов)",
    )
    today = timezone.localdate()
    for t in payable:
        t.paid = True
        t.paid_at = today
        t.expense = exp
        t.save(update_fields=["paid", "paid_at", "expense", "updated_at"])
    messages.success(request, _("Выплачено %(s)s сом технику %(t)s") % {"s": f"{total:.0f}", "t": tech.name})
    return redirect("technician_payouts")


@login_required
@require_POST
def warranty_case_add(request, pk):
    """Зафиксировать гарантийный случай по технику."""
    tech = get_object_or_404(Technician, pk=pk)
    task = TechnicianTask.objects.filter(pk=request.POST.get("task"), technician=tech).first()
    TechnicianWarrantyCase.objects.create(
        technician=tech, task=task, patient=(task.patient if task else None),
        reason=(request.POST.get("reason") or "").strip(), created_by=request.user,
    )
    messages.success(request, _("Гарантийный случай зафиксирован"))
    return redirect("technician_detail", pk=pk)
