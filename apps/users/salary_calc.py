"""Зарплата по схеме «% от услуги».

Считается по реальным оплатам за период (кассовый метод):

1. Оплата делится по приёмам через PaymentAllocation; у старых оплат без
   распределения берётся приём, к которому она привязана. Оплата без приёма
   (предоплата «на баланс») в зарплату не идёт, пока не распределена.
2. Внутри приёма сумма делится между услугами пропорционально их стоимости
   (с учётом построчной скидки и общей скидки приёма). Деньги по услуге
   получает врач этой услуги (TreatmentCure.doctor), поэтому два врача на
   одном приёме считаются каждый за своё.
3. Из доли услуги вычитается себестоимость (работа техника / заказ
   лаборатории) в той же пропорции, затем берётся процент категории услуги.
4. Скидка: при ClinicSettings.salary_discount_shared (по умолчанию) процент
   берётся с оплаченной суммы, т.е. скидку делят клиника и врач; иначе — с
   полной цены услуги, скидку несёт клиника.

Переплата сверх суммы приёма в зарплату не идёт; возврат по приёму уменьшает
начисление в том периоде, когда он сделан.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal(0)
CENT = Decimal("0.01")


def _q(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def _cure_cost(cure):
    """Себестоимость услуги: заказ технику/лаборатории (без отменённых)."""
    from apps.technicians.models import TechnicianTask
    task = getattr(cure, "lab_order_obj", None)
    if task is None and cure.lab_order_id:
        task = cure.lab_order
    if task is None or task.status == TechnicianTask.STATUS_CANCELLED:
        return ZERO
    return task.amount or ZERO


def _treatment_entries(treatment_ids):
    """Все денежные движения по приёмам в хронологическом порядке:
    {treatment_id: [(payment, signed_amount), ...]}."""
    from apps.finance.models import Payment, PaymentAllocation

    entries = defaultdict(list)
    allocated_payment_ids = set()
    for a in (PaymentAllocation.objects.filter(treatment_id__in=treatment_ids)
              .select_related("payment", "payment__patient")):
        sign = -1 if a.payment.type == Payment.TYPE_REFUND else 1
        entries[a.treatment_id].append((a.payment, sign * a.amount))
        allocated_payment_ids.add(a.payment_id)
    # Оплаты без распределения (старые) и возвраты — по привязанному приёму.
    for p in (Payment.objects.filter(treatment_id__in=treatment_ids)
              .exclude(pk__in=allocated_payment_ids).select_related("patient")):
        sign = -1 if p.type == Payment.TYPE_REFUND else 1
        entries[p.treatment_id].append((p, sign * p.amount))
    for lst in entries.values():
        lst.sort(key=lambda e: (e[0].created_at, e[0].pk))
    return entries


def service_salary(doctor, date_from, date_to, scheme=None, discount_shared=None):
    """Расшифровка зарплаты врача за [date_from, date_to].

    Возвращает {"payments": [...], "total": Decimal, "base": Decimal,
    "cost": Decimal, "discount": Decimal, "discount_shared": bool}.
    Каждая оплата: дата, пациент, сумма и строки по услугам врача
    (приём, услуга, зуб, категория, %, база, себестоимость, доля)."""
    from django.utils import timezone
    from apps.finance.models import Payment, PaymentAllocation
    from apps.treatments.models import Treatment, TreatmentCure
    from apps.settings_clinic.models import ClinicSettings

    if scheme is None:
        scheme = getattr(doctor, "salary_scheme", None)
    if discount_shared is None:
        discount_shared = getattr(ClinicSettings.get(), "salary_discount_shared", True)

    period = {"created_at__date__gte": date_from, "created_at__date__lte": date_to}
    in_period = Payment.objects.filter(**period)
    doctor_treatments = TreatmentCure.objects.filter(doctor=doctor).values("treatment_id")
    treatment_ids = set(
        PaymentAllocation.objects.filter(payment__in=in_period, treatment_id__in=doctor_treatments)
        .values_list("treatment_id", flat=True))
    treatment_ids |= set(
        in_period.filter(treatment_id__in=doctor_treatments, allocations__isnull=True)
        .values_list("treatment_id", flat=True))
    treatment_ids.discard(None)

    treatments = {
        t.pk: t for t in Treatment.objects.filter(pk__in=treatment_ids)
        .exclude(status__in=Treatment.NON_BILLABLE_STATUSES)
    }
    cures = defaultdict(list)
    for c in (TreatmentCure.objects.filter(treatment_id__in=treatments.keys())
              .select_related("service", "service__category", "lab_order", "lab_order_obj")
              .order_by("pk")):
        cures[c.treatment_id].append(c)

    cat_pct = {cp.category_id: cp.percent for cp in scheme.category_percents.all()} if scheme else {}
    default_pct = scheme.percent if scheme else ZERO

    by_payment = {}
    totals = {"total": ZERO, "base": ZERO, "cost": ZERO, "discount": ZERO}
    for tid, movements in _treatment_entries(treatments.keys()).items():
        t = treatments[tid]
        t_cures = cures.get(tid) or []
        sub_total = sum((c.subtotal for c in t_cures), ZERO)
        fixed_discount = t.discount or ZERO
        billed = sub_total - fixed_discount
        mine = [c for c in t_cures if c.doctor_id == doctor.pk]
        if billed <= 0 or not mine:
            continue
        cum = ZERO  # сколько уже засчитано в оплату приёма
        for payment, amount in movements:
            if amount >= 0:
                effective = min(amount, max(ZERO, billed - cum))
            else:
                effective = -min(-amount, cum)
            cum += effective
            pdate = timezone.localtime(payment.created_at).date()
            if not (date_from <= pdate <= date_to) or effective == 0:
                continue
            share = effective / billed
            rows = []
            for c in mine:
                net = c.subtotal - (fixed_discount * c.subtotal / sub_total if sub_total else ZERO)
                gross = c.price * c.quantity
                base = (net if discount_shared else gross) * share
                discount = (gross - net) * share
                cost = _cure_cost(c) * share
                value = base - cost
                value = max(ZERO, value) if effective > 0 else min(ZERO, value)
                category = c.service.category if c.service_id else None
                pct = cat_pct.get(category.pk, default_pct) if category else default_pct
                earned = _q(value * pct / 100)
                rows.append({
                    "cure_id": c.pk,
                    "service": c.service.name,
                    "tooth": c.tooth_number,
                    "quantity": c.quantity,
                    "category": category.name if category else "Без категории",
                    "percent": pct,
                    "price": _q(gross),
                    "base": _q(base),
                    "discount": _q(discount),
                    "cost": _q(cost),
                    "earned": earned,
                })
                totals["base"] += _q(base)
                totals["discount"] += _q(discount)
                totals["cost"] += _q(cost)
                totals["total"] += earned
            pay = by_payment.setdefault(payment.pk, {
                "payment_id": payment.pk,
                "created_at": payment.created_at,
                "date": timezone.localtime(payment.created_at).strftime("%d.%m.%Y %H:%M"),
                "patient": payment.patient.full_name if payment.patient_id else "—",
                "amount": payment.amount,
                "is_refund": payment.type == Payment.TYPE_REFUND,
                "method": payment.get_method_display(),
                "treatments": [],
                "earned": ZERO,
            })
            pay["treatments"].append({
                "treatment_id": tid,
                "number": t.display_number,
                "date": timezone.localtime(t.created_at).strftime("%d.%m.%Y"),
                "amount": _q(effective),
                "billed": _q(billed),
                "other_doctors": len(mine) < len(t_cures),
                "rows": rows,
            })
            pay["earned"] += sum((r["earned"] for r in rows), ZERO)

    payments = sorted(by_payment.values(), key=lambda p: (p["created_at"], p["payment_id"]))
    return {"payments": payments, "discount_shared": discount_shared, **totals}


def payouts_qs(doctor, date_from, date_to):
    """Выплаты, относящиеся к периоду: по концу периода, за который выплата
    сделана (зарплата за сентябрь, выданная 5 октября, — это сентябрь), а без
    периода — по дате выплаты."""
    from django.db.models import Q
    from .models_salary import SalaryPayout
    return SalaryPayout.objects.filter(doctor=doctor).filter(
        Q(period_to__gte=date_from, period_to__lte=date_to)
        | Q(period_to__isnull=True, paid_on__gte=date_from, paid_on__lte=date_to))


def payouts_total(doctor, date_from, date_to):
    from django.db.models import Sum
    return payouts_qs(doctor, date_from, date_to).aggregate(s=Sum("amount"))["s"] or ZERO


def unpaid_since(doctor):
    """С какой даты врачу не выплачено: день после периода последней выплаты
    (или её даты, если период не указан). None — выплат не было."""
    from datetime import timedelta
    from .models_salary import SalaryPayout
    last = SalaryPayout.objects.filter(doctor=doctor).order_by("-paid_on", "-id").first()
    if last is None:
        return None
    return (last.period_to or last.paid_on) + timedelta(days=1)
