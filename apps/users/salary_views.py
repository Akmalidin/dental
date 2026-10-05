"""Зарплата врача в новом интерфейсе: расшифровка по оплатам («% от услуги»),
выплаты и печатное «Объяснение» (сохраняется в PDF из окна печати).
Директор и суперадмин видят всех и фиксируют выплаты; любой сотрудник —
только свою зарплату («Моя зарплата»), без кнопок выплат."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import role_required
from .models import clinic_staff
from .models_salary import SalaryScheme, SalaryPayout
from .salary_calc import service_salary, payouts_qs, payouts_total, unpaid_since


def _staff_member(pk):
    from apps.tenancy import get_current_clinic
    return get_object_or_404(clinic_staff(get_current_clinic()), pk=pk)


def _is_manager(user):
    return user.is_superadmin or user.has_role("admin_main")


def _viewable_member(request, pk):
    """Директор/суперадмин — любой сотрудник клиники, остальные — только сами."""
    from django.http import Http404
    if not _is_manager(request.user) and pk != request.user.pk:
        raise Http404
    return _staff_member(pk)


def _parse_date(value, default=None):
    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return default


def _period(request, doctor):
    """Период из ?from=&to=; по умолчанию — «не выплачено с» (день после
    последней выплаты) или начало месяца, по сегодня."""
    today = timezone.localdate()
    since = unpaid_since(doctor)
    default_from = since if since and since <= today else today.replace(day=1)
    date_from = _parse_date(request.GET.get("from"), default_from)
    date_to = _parse_date(request.GET.get("to"), today)
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to, since


def _salary_summary(doctor, date_from, date_to):
    scheme = getattr(doctor, "salary_scheme", None)
    is_service = bool(scheme and scheme.scheme_type == SalaryScheme.TYPE_PERCENT_SERVICE)
    calc = service_salary(doctor, date_from, date_to, scheme=scheme) if is_service else None
    if calc is not None:
        earned = calc["total"]
    else:
        from .views import _salary_rows
        row = next((r for r in _salary_rows(date_from, date_to) if r["doctor"].pk == doctor.pk), None)
        earned = row["salary"] if row else Decimal(0)
    paid = payouts_total(doctor, date_from, date_to)
    return scheme, is_service, calc, earned, paid


def _f(v):
    return float(v or 0)


@login_required
def newui_salary_me(request):
    """«Моя зарплата» — своя расшифровка для любого сотрудника."""
    return newui_salary_doctor(request, request.user.pk)


@login_required
def newui_salary_doctor(request, pk):
    from .newui_views import _render
    doctor = _viewable_member(request, pk)
    manager = _is_manager(request.user)
    date_from, date_to, since = _period(request, doctor)
    scheme, is_service, calc, earned, paid = _salary_summary(doctor, date_from, date_to)
    payments = []
    for p in (calc["payments"] if calc else []):
        payments.append({
            "paymentId": p["payment_id"], "date": p["date"], "patient": p["patient"],
            "patientId": p["patient_id"],
            "amount": _f(p["amount"]), "isRefund": p["is_refund"], "method": p["method"],
            "earned": _f(p["earned"]),
            "treatments": [{
                "id": t["treatment_id"], "number": t["number"], "date": t["date"],
                "amount": _f(t["amount"]), "billed": _f(t["billed"]), "otherDoctors": t["other_doctors"],
                "rows": [{
                    "service": r["service"], "tooth": r["tooth"], "quantity": r["quantity"],
                    "category": r["category"], "percent": _f(r["percent"]), "price": _f(r["price"]),
                    "base": _f(r["base"]), "discount": _f(r["discount"]), "cost": _f(r["cost"]),
                    "earned": _f(r["earned"]),
                } for r in t["rows"]],
            } for t in p["treatments"]],
        })
    payouts = [{
        "id": po.pk, "amount": _f(po.amount), "paidOn": po.paid_on.strftime("%d.%m.%Y"),
        "period": (f"{po.period_from:%d.%m.%Y} — {po.period_to:%d.%m.%Y}"
                   if po.period_from and po.period_to else ""),
        "comment": po.comment, "by": po.created_by.name if po.created_by else "",
    } for po in SalaryPayout.objects.filter(doctor=doctor).select_related("created_by")[:50]]
    data = {
        "doctorId": doctor.pk,
        "canManage": manager,
        "isSelf": doctor.pk == request.user.pk,
        "doctorName": doctor.name,
        "schemeType": scheme.scheme_type if scheme else "",
        "schemeLabel": scheme.get_scheme_type_display() if scheme else "",
        "isService": is_service,
        "from": date_from.isoformat(), "to": date_to.isoformat(),
        "fromLabel": date_from.strftime("%d.%m.%Y"), "toLabel": date_to.strftime("%d.%m.%Y"),
        "unpaidSince": since.isoformat() if since else "",
        "unpaidSinceLabel": since.strftime("%d.%m.%Y") if since else "",
        "monthStart": timezone.localdate().replace(day=1).isoformat(),
        "today": timezone.localdate().isoformat(),
        "earned": _f(earned), "paidOut": _f(paid), "remaining": _f(earned - paid),
        "base": _f(calc["base"]) if calc else 0, "cost": _f(calc["cost"]) if calc else 0,
        "discount": _f(calc["discount"]) if calc else 0,
        "discountShared": calc["discount_shared"] if calc else True,
        "payments": payments,
        "payouts": payouts,
    }
    return _render(request, "salary" if manager else "mysalary", "salary_doctor.html", {"salaryDoctor": data})


@login_required
def newui_salary_explain(request, pk):
    """«Объяснение» для врача: печатная форма, сохраняется в PDF из окна печати."""
    from apps.settings_clinic.models import ClinicSettings
    doctor = _viewable_member(request, pk)
    date_from, date_to, _since = _period(request, doctor)
    scheme, is_service, calc, earned, paid = _salary_summary(doctor, date_from, date_to)
    cs = ClinicSettings.get()
    categories = []
    if scheme and is_service:
        categories = [(cp.category.name, cp.percent) for cp in
                      scheme.category_percents.select_related("category").order_by("category__sort_order", "category__name")]
    return render(request, "users/salary_explain_print.html", {
        "doctor": doctor, "scheme": scheme, "is_service": is_service, "calc": calc,
        "earned": earned, "paid": paid, "remaining": earned - paid,
        "date_from": date_from, "date_to": date_to, "cs": cs,
        "cur": cs.currency_label, "categories": categories,
        "generated": timezone.localtime(),
        "payouts": payouts_qs(doctor, date_from, date_to),
    })


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def newui_salary_payout_add(request, pk):
    doctor = _staff_member(pk)
    try:
        amount = Decimal(str(request.POST.get("amount", "")).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        amount = Decimal(0)
    if amount <= 0 or amount > Decimal("999999999"):
        return JsonResponse({"ok": False, "error": "Укажите сумму выплаты"}, status=400)
    paid_on = _parse_date(request.POST.get("paid_on"), timezone.localdate())
    period_from = _parse_date(request.POST.get("period_from"))
    period_to = _parse_date(request.POST.get("period_to"))
    if period_from and period_to and period_from > period_to:
        period_from, period_to = period_to, period_from
    po = SalaryPayout.objects.create(
        doctor=doctor, amount=amount, paid_on=paid_on,
        period_from=period_from, period_to=period_to if period_from else None,
        comment=(request.POST.get("comment") or "").strip()[:300],
        created_by=request.user,
    )
    return JsonResponse({"ok": True, "id": po.pk})


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def newui_salary_payout_delete(request, pk):
    po = get_object_or_404(SalaryPayout, pk=pk)
    _staff_member(po.doctor_id)
    po.delete()
    return JsonResponse({"ok": True})


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def newui_salary_settings(request):
    """Переключатель «Скидка уменьшает зарплату врача» (Настройки клиники)."""
    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()
    cs.salary_discount_shared = request.POST.get("discount_shared") in ("1", "on", "true")
    cs.save(update_fields=["salary_discount_shared", "updated_at"])
    return JsonResponse({"ok": True, "discountShared": cs.salary_discount_shared})
