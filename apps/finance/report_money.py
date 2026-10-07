"""Деньги для отчётов: «Оплачено» и «Оказано услуг» по врачам и услугам.

Раньше «Выручка» в отчётах значила разное: вверху — деньги, полученные в
кассе за месяц, а по врачам/услугам — сумма счетов (оплачены или нет, без
скидки). Теперь два явных показателя:
- оказано (billed): счёт приёма за вычетом скидки, приёмы, созданные в периоде;
- оплачено (paid): деньги, полученные в периоде (распределения платежей
  этого периода на приёмы минус возвраты), плюс «Аванс / без приёма» —
  оплата, ещё не привязанная ни к одному приёму. Сумма «оплачено» по
  врачам = «Оплачено за месяц» вверху отчёта.
Если в приёме несколько врачей/услуг, сумма делится пропорционально их
строкам (TreatmentCure.subtotal)."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

ADVANCE = "Аванс / без приёма"


def _d(v):
    return v or Decimal(0)


def _shares(treatments):
    """{treatment_id: [(doctor_name, service_name, доля)]}"""
    from apps.treatments.models import TreatmentCure
    rows = defaultdict(list)
    for c in (TreatmentCure.objects.filter(treatment_id__in=[t.pk for t in treatments])
              .select_related("service", "doctor")):
        rows[c.treatment_id].append(c)
    out = {}
    for t in treatments:
        cures = rows.get(t.pk) or []
        total = sum((c.subtotal for c in cures), Decimal(0))
        doc = t.doctor.name if t.doctor_id else "—"
        if not cures or total <= 0:
            out[t.pk] = [(doc, "Без услуги", Decimal(1))]
            continue
        out[t.pk] = [((c.doctor.name if c.doctor_id else doc), (c.service.name if c.service_id else "Без услуги"),
                      c.subtotal / total) for c in cures]
    return out


def money(start, branch_id=None):
    """Возвращает {"doctors": {...}, "services": {...}, "paid_total", "billed_total"};
    в doctors/services: name -> {"billed", "paid", "count"} (count — приёмов/строк в периоде)."""
    from apps.treatments.models import Treatment
    from .models import Payment, PaymentAllocation

    billed_t = list(Treatment.objects.filter(created_at__date__gte=start, is_deleted=False)
                    .exclude(status__in=["cancelled", "draft"]).select_related("doctor"))
    if branch_id:
        billed_t = [t for t in billed_t if t.branch_id == int(branch_id)]

    pay_qs = Payment.objects.filter(created_at__date__gte=start)
    if branch_id:
        pay_qs = pay_qs.filter(branch_id=branch_id)
    allocs = list(PaymentAllocation.objects.filter(payment__in=pay_qs.filter(type=Payment.TYPE_INCOME))
                  .values_list("treatment_id", "amount"))
    refunds = list(pay_qs.filter(type=Payment.TYPE_REFUND, treatment__isnull=False)
                   .values_list("treatment_id", "amount"))
    income = _d(pay_qs.filter(type=Payment.TYPE_INCOME).aggregate(s=Sum("amount"))["s"])
    refund_all = _d(pay_qs.filter(type=Payment.TYPE_REFUND).aggregate(s=Sum("amount"))["s"])

    paid_by_t = defaultdict(Decimal)
    for tid, a in allocs:
        paid_by_t[tid] += a
    for tid, a in refunds:
        paid_by_t[tid] -= a
    need = {t.pk: t for t in billed_t}
    extra = [tid for tid in paid_by_t if tid not in need]
    if extra:
        for t in Treatment.all_objects.filter(pk__in=extra).select_related("doctor"):
            need[t.pk] = t
    shares = _shares(list(need.values()))

    doctors = defaultdict(lambda: {"billed": Decimal(0), "paid": Decimal(0), "count": 0})
    services = defaultdict(lambda: {"billed": Decimal(0), "paid": Decimal(0), "count": 0})
    for t in billed_t:
        amount = _d(t.total_amount) - _d(t.discount)
        seen = set()
        for doc, svc, share in shares[t.pk]:
            doctors[doc]["billed"] += amount * share
            services[svc]["billed"] += amount * share
            services[svc]["count"] += 1
            if doc not in seen:
                doctors[doc]["count"] += 1
                seen.add(doc)
    for tid, amount in paid_by_t.items():
        for doc, svc, share in shares.get(tid, [("—", "Без услуги", Decimal(1))]):
            doctors[doc]["paid"] += amount * share
            services[svc]["paid"] += amount * share
    # оплата, не привязанная к приёмам, и возвраты без приёма — отдельной строкой,
    # чтобы сумма по врачам совпадала с «Оплачено за месяц»
    rest = income - refund_all - sum(paid_by_t.values(), Decimal(0))
    if abs(rest) >= 1:
        doctors[ADVANCE]["paid"] += rest
    return {
        "doctors": doctors, "services": services,
        "paid_total": income - refund_all,
        "billed_total": sum((_d(t.total_amount) - _d(t.discount) for t in billed_t), Decimal(0)),
    }
