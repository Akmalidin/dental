"""Только чтение: сверка кассы и денег по всем клиникам (workflow diag-cashdesk-audit).

Ищет расхождения, на которые жалуются кассиры: долг пациента не равен сумме
долгов по приёмам, оплата приёма считана двумя разными способами, платёж
распределён не на всю сумму, двойные платежи, смены без закрытия, недостача
при закрытии, заявки «В кассу», висящие после оплаты. Ничего не меняет."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.utils import timezone


def _d(v):
    return v or Decimal(0)


class Command(BaseCommand):
    help = "Сверка кассы и денег (только чтение)"

    def handle(self, *args, **opts):
        from apps.finance.models import CashShift, Expense, Payment, PaymentAllocation
        from apps.notifications.models import Notification
        from apps.patients.models import Patient
        from apps.tenancy import unscoped
        from apps.treatments.models import Treatment
        from apps.users.models import Clinic

        out = self.stdout.write
        with unscoped():
            clinics = {c.pk: c.name for c in Clinic.objects.all()}
            now = timezone.now()

            # 1. Оплата приёма: paid_amount против суммы распределений и против платежей с FK
            alloc = dict(PaymentAllocation.objects.values("treatment").annotate(s=Sum("amount"))
                         .values_list("treatment", "s"))
            fk_in = dict(Payment.all_clinics.filter(type="income", treatment__isnull=False)
                         .values("treatment").annotate(s=Sum("amount")).values_list("treatment", "s"))
            fk_ref = dict(Payment.all_clinics.filter(type="refund", treatment__isnull=False)
                          .values("treatment").annotate(s=Sum("amount")).values_list("treatment", "s"))
            bad_paid, overpaid = defaultdict(list), defaultdict(list)
            for t in (Treatment.all_objects.filter(is_deleted=False).exclude(status__in=["cancelled", "draft"])
                      .only("pk", "clinic_id", "paid_amount", "total_amount", "discount", "patient_id")):
                a = _d(alloc.get(t.pk))
                if abs(_d(t.paid_amount) - a) >= 1:
                    bad_paid[t.clinic_id].append((t.pk, t.patient_id, float(t.paid_amount), float(a),
                                                  float(_d(fk_in.get(t.pk)) - _d(fk_ref.get(t.pk)))))
                billed = _d(t.total_amount) - _d(t.discount)
                if _d(t.paid_amount) - billed >= 1:
                    overpaid[t.clinic_id].append((t.pk, float(billed), float(t.paid_amount)))
            out("\n=== 1. Приёмы: оплачено (paid_amount) ≠ распределено платежами ===")
            for cid, rows in bad_paid.items():
                out("%s: %d приёмов" % (clinics.get(cid), len(rows)))
                for r in rows[:8]:
                    out("   приём %s пациент %s: paid=%.0f, распределено=%.0f, по ссылке платежа=%.0f" % r)
            out("\n=== 1b. Приёмы оплачены больше счёта ===")
            for cid, rows in overpaid.items():
                out("%s: %d (пример: %s)" % (clinics.get(cid), len(rows), rows[:4]))

            # 2. Баланс пациента против сохранённого и против суммы долгов по приёмам
            inc = dict(Payment.all_clinics.filter(type="income").values("patient").annotate(s=Sum("amount"))
                       .values_list("patient", "s"))
            ref = dict(Payment.all_clinics.filter(type="refund").values("patient").annotate(s=Sum("amount"))
                       .values_list("patient", "s"))
            tr = defaultdict(lambda: [Decimal(0), Decimal(0)])
            for pid, tot, disc, paid in (Treatment.all_objects.filter(is_deleted=False)
                                         .exclude(status__in=["cancelled", "draft"])
                                         .values_list("patient_id", "total_amount", "discount", "paid_amount")):
                tr[pid][0] += _d(tot) - _d(disc)
                tr[pid][1] += max(Decimal(0), _d(tot) - _d(disc) - _d(paid))
            stale, mismatch = defaultdict(list), defaultdict(list)
            for p in Patient.all_objects.filter(is_deleted=False).only("pk", "clinic_id", "balance"):
                real = _d(inc.get(p.pk)) - _d(ref.get(p.pk)) - tr[p.pk][0]
                if abs(real - _d(p.balance)) >= 1:
                    stale[p.clinic_id].append((p.pk, float(p.balance), float(real)))
                debt_patient = max(Decimal(0), -real)
                debt_visits = tr[p.pk][1]
                if abs(debt_patient - debt_visits) >= 1:
                    mismatch[p.clinic_id].append((p.pk, float(debt_patient), float(debt_visits)))
            out("\n=== 2. Баланс пациента устарел (сохранён ≠ пересчёт) ===")
            for cid, rows in stale.items():
                out("%s: %d (пример [id, сохранён, верно]: %s)" % (clinics.get(cid), len(rows), rows[:5]))
            out("\n=== 2b. Долг пациента ≠ сумма долгов по его приёмам (касса показывает разное) ===")
            for cid, rows in mismatch.items():
                out("%s: %d (пример [id, долг пациента, сумма по приёмам]: %s)" % (clinics.get(cid), len(rows), rows[:6]))

            # 3. Платежи: распределено не на всю сумму / больше суммы
            alloc_by_pay = dict(PaymentAllocation.objects.values("payment").annotate(s=Sum("amount"))
                                .values_list("payment", "s"))
            under, over = defaultdict(list), defaultdict(list)
            for p in Payment.all_clinics.filter(type="income").only("pk", "clinic_id", "amount", "patient_id"):
                a = _d(alloc_by_pay.get(p.pk))
                if p.amount - a >= 1:
                    under[p.clinic_id].append((p.pk, p.patient_id, float(p.amount), float(a)))
                elif a - p.amount >= 1:
                    over[p.clinic_id].append((p.pk, float(p.amount), float(a)))
            out("\n=== 3. Оплаты распределены по приёмам не полностью (аванс/переплата без приёма) ===")
            for cid, rows in under.items():
                out("%s: %d, сумма нераспределённого %.0f (пример: %s)" % (
                    clinics.get(cid), len(rows), sum(r[2] - r[3] for r in rows), rows[:4]))
            out("\n=== 3b. Распределено больше суммы платежа ===")
            for cid, rows in over.items():
                out("%s: %d (пример: %s)" % (clinics.get(cid), len(rows), rows[:4]))

            # 4. Возвраты
            out("\n=== 4. Возвраты ===")
            for cid, n, s in (Payment.all_clinics.filter(type="refund").values("clinic")
                              .annotate(n=Count("id"), s=Sum("amount")).values_list("clinic", "n", "s")):
                linked = Payment.all_clinics.filter(type="refund", clinic_id=cid, treatment__isnull=False).count()
                out("%s: %d возвратов на %.0f, из них с привязкой к приёму %d" % (clinics.get(cid), n, s, linked))

            # 5. Двойные платежи: тот же пациент и сумма в течение 3 минут
            out("\n=== 5. Возможные двойные платежи (тот же пациент и сумма ≤ 3 мин) ===")
            dup = defaultdict(list)
            last = {}
            for p in (Payment.all_clinics.filter(created_at__gte=now - timedelta(days=60))
                      .order_by("patient_id", "amount", "created_at")
                      .only("pk", "clinic_id", "patient_id", "amount", "type", "created_at")):
                key = (p.patient_id, p.amount, p.type)
                prev = last.get(key)
                if prev and (p.created_at - prev.created_at) <= timedelta(minutes=3):
                    dup[p.clinic_id].append((prev.pk, p.pk, float(p.amount),
                                             timezone.localtime(p.created_at).strftime("%d.%m %H:%M")))
                last[key] = p
            for cid, rows in dup.items():
                out("%s: %d (пример: %s)" % (clinics.get(cid), len(rows), rows[:6]))

            # 6. Смены
            out("\n=== 6. Кассовые смены ===")
            for s in CashShift.all_clinics.filter(status="open").select_related("branch"):
                out("ОТКРЫТА %s / %s с %s (%d дн.)" % (clinics.get(s.clinic_id), s.branch.name,
                                                      timezone.localtime(s.opened_at).strftime("%d.%m.%Y %H:%M"),
                                                      (now - s.opened_at).days))
            for s in (CashShift.all_clinics.filter(status="closed", closed_at__gte=now - timedelta(days=45))
                      .select_related("branch").order_by("-closed_at")[:40]):
                end = s.closed_at
                cash = Decimal(0)
                for p in Payment.all_clinics.filter(branch=s.branch, created_at__gte=s.opened_at,
                                                    created_at__lte=end, method="cash"):
                    cash += p.amount if p.type == "income" else -p.amount
                exp = _d(Expense.all_clinics.filter(branch=s.branch, created_at__gte=s.opened_at,
                                                    created_at__lte=end).aggregate(s=Sum("amount"))["s"])
                expected = _d(s.opening_cash) + cash
                actual = _d(s.closing_cash_actual)
                out("закрыта %s / %s %s→%s: нач %.0f + нал %.0f = ожид %.0f, факт %.0f, разница %.0f; "
                    "расходы за смену %.0f" % (
                        clinics.get(s.clinic_id), s.branch.name,
                        timezone.localtime(s.opened_at).strftime("%d.%m %H:%M"),
                        timezone.localtime(end).strftime("%d.%m %H:%M"),
                        s.opening_cash, cash, expected, actual, actual - expected, exp))
            # платежи вне смен (последние 30 дней)
            out("\n=== 6b. Платежи, принятые без открытой смены (30 дней) ===")
            shifts = defaultdict(list)
            for s in CashShift.all_clinics.all():
                shifts[s.branch_id].append((s.opened_at, s.closed_at or now))
            outside = defaultdict(lambda: [0, Decimal(0)])
            for p in Payment.all_clinics.filter(created_at__gte=now - timedelta(days=30)).only(
                    "branch_id", "clinic_id", "created_at", "amount", "type"):
                if not any(a <= p.created_at <= b for a, b in shifts.get(p.branch_id, [])):
                    outside[p.clinic_id][0] += 1
                    outside[p.clinic_id][1] += p.amount if p.type == "income" else -p.amount
            for cid, (n, s) in outside.items():
                out("%s: %d платежей на %.0f вне смены" % (clinics.get(cid), n, s))
            out("\n=== 6c. Платежи: филиал из другой клиники ===")
            cross = Payment.all_clinics.exclude(branch__clinic_id=None).exclude(
                branch__clinic_id=models_F("clinic_id")).count()
            out("всего: %d" % cross)

            # 7. Очередь «В кассу»
            out("\n=== 7. Очередь «В кассу» (непрочитанные заявки) ===")
            from urllib.parse import parse_qs, urlparse
            qrows = defaultdict(lambda: [0, 0, 0])
            seen = set()
            for n in Notification.objects.filter(type="payment", is_read=False,
                                                 link__startswith="/finance/payments/?patient="):
                if (n.clinic_id, n.link) in seen:
                    continue
                seen.add((n.clinic_id, n.link))
                q = parse_qs(urlparse(n.link).query)
                pid = int(q["patient"][0]) if q.get("patient") else None
                pat = Patient.all_objects.filter(pk=pid).first() if pid else None
                qrows[n.clinic_id][0] += 1
                if n.created_at < now - timedelta(days=2):
                    qrows[n.clinic_id][1] += 1
                if pat is not None and pat.debt <= 0:
                    qrows[n.clinic_id][2] += 1
            for cid, (total, old, paid) in qrows.items():
                out("%s: заявок %d, старше 2 дней %d, у пациента уже нет долга %d" % (
                    clinics.get(cid), total, old, paid))

            # 8. Сводка за 30 дней по способам оплаты и «кто принял»
            out("\n=== 8. Оплаты за 30 дней: врачом напрямую (не через кассу) ===")
            for cid, n, s in (Payment.all_clinics.filter(created_at__gte=now - timedelta(days=30), via_cashier=False,
                                                         type="income")
                              .values("clinic").annotate(n=Count("id"), s=Sum("amount"))
                              .values_list("clinic", "n", "s")):
                out("%s: %d на %.0f" % (clinics.get(cid), n, s))
        out("\nГотово.")


def models_F(name):
    from django.db.models import F
    return F(name)
