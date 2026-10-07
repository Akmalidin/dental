"""Единый расчёт «сколько оплачено за приём» и сверка распределений.

Раньше paid_amount приёма считался двумя способами: Payment.save() — по
платежам со ссылкой treatment, а касса — по распределениям PaymentAllocation.
Кто сохранял последним, тот и прав, и долг по приёму расходился с долгом
пациента. Кроме того, оплата, принятая раньше, чем заведён приём (аванс), или
переплата так и оставались нераспределёнными: пациент ничего не должен, а в
«Пациентах на сегодня» его приём висел с долгом.

Правило теперь одно:
  оплачено за приём = распределения платежей на него − возвраты по нему.
reconcile_patient() держит распределения в порядке: снимает их с отменённых/
удалённых приёмов и сверх счёта, а свободные остатки оплат раскладывает на
неоплаченные приёмы от старых к новым. Вызывается из Patient.recalc_balance(),
т.е. при каждом изменении платежей и приёмов."""
import logging
from decimal import Decimal

from django.db.models import Sum

log = logging.getLogger("apps")


def _d(v):
    return v or Decimal(0)


def treatment_paid(treatment_id):
    from .models import Payment, PaymentAllocation
    alloc = _d(PaymentAllocation.objects.filter(treatment_id=treatment_id).aggregate(s=Sum("amount"))["s"])
    refund = _d(Payment.all_clinics.filter(treatment_id=treatment_id, type=Payment.TYPE_REFUND)
                .aggregate(s=Sum("amount"))["s"])
    return alloc - refund


def recompute_treatment_paid(treatment_id):
    from apps.treatments.models import Treatment
    if treatment_id:
        Treatment.all_objects.filter(pk=treatment_id).update(paid_amount=treatment_paid(treatment_id))


def reconcile_patient(patient_id):
    """Привести распределения оплат пациента в порядок (см. описание модуля).
    Возвращает число изменённых приёмов."""
    from .models import Payment, PaymentAllocation
    from apps.treatments.models import Treatment
    if not patient_id:
        return 0
    allocs = list(PaymentAllocation.objects.filter(payment__patient_id=patient_id)
                  .select_related("treatment", "payment").order_by("-payment__created_at", "-pk"))
    treatments = list(Treatment.all_objects.filter(patient_id=patient_id).order_by("created_at", "pk"))
    billable = {t.pk: t for t in treatments
                if not t.is_deleted and t.status not in ("cancelled", "draft")}
    affected = set()

    # 1. Распределения на отменённые/удалённые/черновые приёмы — деньги свободны
    for a in allocs:
        if a.treatment_id not in billable:
            affected.add(a.treatment_id)
            a.delete()
    allocs = [a for a in allocs if a.treatment_id in billable]

    # 2. Сверх счёта приёма (скидку дали после оплаты, двойной платёж…) — снимаем
    #    с самых новых распределений; излишек становится авансом пациента
    by_t = {}
    for a in allocs:
        by_t.setdefault(a.treatment_id, []).append(a)
    for tid, rows in by_t.items():
        t = billable[tid]
        excess = sum((a.amount for a in rows), Decimal(0)) - (_d(t.total_amount) - _d(t.discount))
        for a in rows:   # уже от новых к старым
            if excess <= 0:
                break
            cut = min(excess, a.amount)
            excess -= cut
            affected.add(tid)
            if cut >= a.amount:
                a.delete()
            else:
                a.amount -= cut
                a.save(update_fields=["amount"])

    # 3. Свободные остатки оплат → неоплаченные приёмы (от старых к новым)
    used = {p: _d(s) for p, s in PaymentAllocation.objects.filter(payment__patient_id=patient_id)
            .values("payment").annotate(s=Sum("amount")).values_list("payment", "s")}
    free = []
    for p in Payment.all_clinics.filter(patient_id=patient_id, type=Payment.TYPE_INCOME).order_by("created_at", "pk"):
        rest = p.amount - used.get(p.pk, Decimal(0))
        if rest > 0:
            free.append([p, rest])
    if free:
        got = {t: _d(s) for t, s in PaymentAllocation.objects.filter(treatment_id__in=list(billable))
               .values("treatment").annotate(s=Sum("amount")).values_list("treatment", "s")}
        # сначала — на приём, указанный в самом платеже
        for item in free:
            p, rest = item
            t = billable.get(p.treatment_id)
            if t is None:
                continue
            take = min(_d(t.total_amount) - _d(t.discount) - got.get(t.pk, Decimal(0)), rest)
            if take > 0:
                PaymentAllocation.objects.create(payment=p, treatment=t, amount=take)
                got[t.pk] = got.get(t.pk, Decimal(0)) + take
                item[1] -= take
                affected.add(t.pk)
        free = [x for x in free if x[1] > 0]
        for t in billable.values():
            need = _d(t.total_amount) - _d(t.discount) - got.get(t.pk, Decimal(0))
            while need > 0 and free:
                p, rest = free[0]
                take = min(need, rest)
                PaymentAllocation.objects.create(payment=p, treatment=t, amount=take)
                affected.add(t.pk)
                need -= take
                free[0][1] -= take
                if free[0][1] <= 0:
                    free.pop(0)
            if not free:
                break

    # 4. paid_amount по единой формуле — и для приёмов, где он разошёлся раньше
    for t in treatments:
        if t.pk in affected or abs(_d(t.paid_amount) - treatment_paid(t.pk)) >= Decimal("0.01"):
            recompute_treatment_paid(t.pk)
            affected.add(t.pk)
    return len(affected)
