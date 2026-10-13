"""Рассрочки: страница «Деньги → Рассрочки», блок в карточке пациента,
оформление и отмена. Расчёт — apps.finance.installments."""
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import installments as inst
from .models import InstallmentPlan


def _plans_data():
    plans = [inst.plan_json(p) for p in InstallmentPlan.objects.exclude(
        status=InstallmentPlan.STATUS_CANCELLED).select_related("patient").prefetch_related("items")]
    today = timezone.localdate()
    month_end = inst.add_months(today.replace(day=1), 1)
    expected = 0.0
    for p in plans:
        if p["status"] != InstallmentPlan.STATUS_ACTIVE:
            continue
        for i in p["items"]:
            d = datetime.fromisoformat(i["dueIso"]).date()
            if i["left"] > 0 and d < month_end:
                expected += i["left"]
    active = [p for p in plans if p["status"] == InstallmentPlan.STATUS_ACTIVE]
    active.sort(key=lambda p: (-p["overdue"], p["nextDue"][6:] + p["nextDue"][3:5] + p["nextDue"][:2]))
    return {
        "plans": active + [p for p in plans if p["status"] != InstallmentPlan.STATUS_ACTIVE][:50],
        "activeCount": len(active),
        "leftTotal": sum(p["left"] for p in active),
        "overdueTotal": sum(p["overdue"] for p in active),
        "overdueCount": sum(1 for p in active if p["overdue"] > 0),
        "expectedMonth": expected,
    }


@login_required
def newui_installments(request):
    from apps.users.newui_views import _render
    # статусы обновляем при открытии (оплата могла погасить график)
    for p in InstallmentPlan.objects.filter(status=InstallmentPlan.STATUS_ACTIVE):
        inst.refresh_status(p)
    return _render(request, "installments", "installments.html", {"installments": _plans_data()})


@login_required
def patient_installments(request, pk):
    from apps.patients.models import Patient
    patient = Patient.objects.filter(pk=pk).first()
    if patient is None:
        return JsonResponse({"ok": False}, status=404)
    plans = []
    for p in patient.installment_plans.exclude(status=InstallmentPlan.STATUS_CANCELLED).prefetch_related("items"):
        inst.refresh_status(p)
        plans.append(inst.plan_json(p))
    return JsonResponse({"ok": True, "plans": plans, "debt": float(max(0, -(patient.balance or 0))),
                         "today": timezone.localdate().isoformat()})


def _dec(v):
    try:
        return Decimal(str(v).replace(" ", "").replace(",", "."))
    except (InvalidOperation, TypeError):
        return None


@login_required
@require_POST
def installment_create(request):
    from apps.patients.models import Patient
    patient = Patient.objects.filter(pk=request.POST.get("patient_id") or 0).first()
    if patient is None:
        return JsonResponse({"ok": False, "error": "Пациент не найден"}, status=404)
    total = _dec(request.POST.get("total"))
    if total is None or total <= 0 or total > Decimal("999999999"):
        return JsonResponse({"ok": False, "error": "Укажите сумму рассрочки"}, status=400)
    try:
        raw = json.loads(request.POST.get("rows") or "[]")
        rows = [(datetime.fromisoformat(r["due"]).date(), _dec(r["amount"])) for r in raw]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "Неверный график"}, status=400)
    if not rows or len(rows) > 120 or any(a is None or a <= 0 for _d, a in rows):
        return JsonResponse({"ok": False, "error": "В графике должны быть платежи с суммой больше нуля"},
                            status=400)
    if any(d < timezone.localdate() for d, _a in rows):
        return JsonResponse({"ok": False, "error": "В графике есть дата в прошлом"}, status=400)
    if sum((a for _d, a in rows), Decimal(0)) != total:
        return JsonResponse({"ok": False, "error": "Сумма платежей графика не равна сумме рассрочки"}, status=400)
    if patient.installment_plans.filter(status=InstallmentPlan.STATUS_ACTIVE).exists():
        return JsonResponse({"ok": False, "error": "У пациента уже есть действующая рассрочка"}, status=400)
    rows.sort(key=lambda r: r[0])
    plan = inst.create_plan(patient, total, rows, user=request.user,
                            note=(request.POST.get("note") or "").strip())
    return JsonResponse({"ok": True, "id": plan.pk})


@login_required
@require_POST
def installment_cancel(request, pk):
    if not (request.user.is_superadmin or request.user.is_admin):
        return JsonResponse({"ok": False, "error": "Отменить рассрочку может администратор"}, status=403)
    plan = InstallmentPlan.objects.filter(pk=pk).first()
    if plan is None:
        return JsonResponse({"ok": False}, status=404)
    plan.status = InstallmentPlan.STATUS_CANCELLED
    plan.save(update_fields=["status", "updated_at"])
    return JsonResponse({"ok": True})


def overdue_count(clinic):
    """Для счётчика в меню: рассрочки с просроченным платежом."""
    if clinic is None:
        return 0
    today = timezone.localdate()
    n = 0
    for p in (InstallmentPlan.all_clinics.filter(clinic=clinic, status=InstallmentPlan.STATUS_ACTIVE,
                                                 items__due_date__lt=today).distinct().prefetch_related("items")):
        if inst.state(p, today)["overdue"] > 0:
            n += 1
    return n
