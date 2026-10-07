"""Исправить расхождения кассы, найденные cashdesk_audit (workflow fix-cashdesk).

Без --apply только показывает, что изменится. Платежи (суммы, даты, кто
принял) НЕ трогает — только производные данные:
- распределения оплат по приёмам и paid_amount (apps.finance.allocation);
- сохранённый баланс пациента;
- заявки «В кассу» по пациентам без долга (гасит);
- клинику у кассовых смен, открытых без неё.
Возможные двойные платежи только перечисляет — удалять их решает человек."""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Исправить расхождения кассы (по умолчанию — пробный прогон)"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **o):
        from apps.finance.allocation import reconcile_patient
        from apps.finance.models import CashShift, Payment
        from apps.notifications.models import Notification
        from apps.patients.models import Patient
        from apps.tenancy import unscoped
        from apps.treatments.models import Treatment
        from urllib.parse import parse_qs, urlparse

        out = self.stdout.write
        apply = o["apply"]
        out("РЕЖИМ: %s" % ("ИСПРАВЛЕНИЕ" if apply else "пробный прогон (ничего не меняется)"))
        with unscoped():
            try:
                with transaction.atomic():
                    # 1. Смены без клиники
                    shifts = list(CashShift.all_clinics.filter(clinic__isnull=True).select_related("branch"))
                    for s in shifts:
                        CashShift.all_clinics.filter(pk=s.pk).update(clinic_id=s.branch.clinic_id)
                    out("Смены без клиники: %d" % len(shifts))

                    # 2. Распределения + балансы
                    ids = set(Payment.all_clinics.values_list("patient_id", flat=True)) | \
                        set(Treatment.all_objects.values_list("patient_id", flat=True))
                    changed_t = changed_b = 0
                    for p in Patient.all_objects.filter(pk__in=ids):
                        before = p.balance
                        changed_t += reconcile_patient(p.pk)
                        p.recalc_balance()
                        if abs((before or 0) - p.balance) >= 1:
                            changed_b += 1
                    out("Пациентов проверено: %d; балансов исправлено: %d; приёмов с пересчитанной оплатой: %d"
                        % (len(ids), changed_b, changed_t))

                    # 3. Заявки «В кассу» без долга
                    closed = 0
                    for n in Notification.objects.filter(type="payment", is_read=False,
                                                         link__startswith="/finance/payments/?patient="):
                        q = parse_qs(urlparse(n.link).query)
                        pid = int(q["patient"][0]) if q.get("patient") else None
                        pat = Patient.all_objects.filter(pk=pid).first() if pid else None
                        if pat is None or pat.debt <= 0:
                            Notification.objects.filter(pk=n.pk).update(is_read=True)
                            closed += 1
                    out("Заявок «В кассу» без долга погашено (копий у администраторов): %d" % closed)
                    if not apply:
                        raise _DryRun()
            except _DryRun:
                pass

            # 4. Возможные двойные платежи — только список
            out("\nВозможные двойные платежи (тот же сотрудник, пациент, сумма, способ ≤ 3 мин) — проверьте вручную:")
            last, n = {}, 0
            for p in (Payment.all_clinics.select_related("patient", "received_by")
                      .order_by("patient_id", "amount", "method", "received_by_id", "created_at")):
                key = (p.patient_id, p.amount, p.method, p.type, p.received_by_id)
                prev = last.get(key)
                if prev and p.created_at - prev.created_at <= timedelta(minutes=3):
                    n += 1
                    out("  клиника %s | %s | %s %.0f | платежи #%s и #%s | %s | принял %s" % (
                        p.clinic_id, p.patient.full_name if p.patient_id else "—", p.get_method_display(),
                        p.amount, prev.pk, p.pk, timezone.localtime(p.created_at).strftime("%d.%m.%Y %H:%M"),
                        p.received_by.name if p.received_by_id else "—"))
                last[key] = p
            out("Итого пар: %d" % n)


class _DryRun(Exception):
    pass
