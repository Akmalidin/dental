"""Автоматическая кассовая смена: закрыть в 02:00 и открыть в 08:00 по
местному времени клиники (Clinic.timezone). Запускается каждые 5 минут
(cron, команда cashshift_auto), поэтому пропущенный из-за перезапуска
сервера момент догоняется при следующем запуске.

- Касается только филиалов, где кассой уже пользовались (была хоть одна смена).
- Закрытие: смена, открытая раньше сегодняшних 02:00, закрывается; наличные
  «по факту» = ожидаемые по Z-отчёту (пересчёт руками больше не вводят).
- Открытие: с 08:00, если с сегодняшних 02:00 в филиале ещё не открывали
  смену. Открыли вручную в 7:00 — вторая не появится; закрыли вручную днём —
  до следующего утра заново сама не откроется."""
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

CLOSE_AT = time(2, 0)
OPEN_AT = time(8, 0)


def _day_cut(local):
    """Начало «кассового дня» — последние 02:00 по местному времени."""
    cut = local.replace(hour=CLOSE_AT.hour, minute=0, second=0, microsecond=0)
    return cut if local >= cut else cut - timedelta(days=1)


def close_shift(shift, user=None, now=None):
    from .models import CashShift
    shift.status = CashShift.STATUS_CLOSED
    shift.closed_at = now or timezone.now()
    shift.closed_by = user
    shift.closing_cash_actual = shift.z_report()["expectedCash"]
    shift.save(update_fields=["status", "closed_at", "closed_by", "closing_cash_actual"])
    return shift


def run(now=None, log=None):
    from django.db import IntegrityError
    from apps.tenancy import unscoped
    from apps.users.models import Branch
    from .models import CashShift
    now = now or timezone.now()
    say = log or (lambda *_: None)
    done = {"closed": 0, "opened": 0}
    with unscoped():
        branch_ids = set(CashShift.all_clinics.values_list("branch_id", flat=True))
        for b in Branch.objects.filter(pk__in=branch_ids, is_active=True).select_related("clinic"):
            clinic = b.clinic
            if clinic is None or not getattr(clinic, "is_active", True):
                continue
            try:
                tz = ZoneInfo(clinic.timezone or "Asia/Bishkek")
            except Exception:  # noqa: BLE001
                tz = ZoneInfo("Asia/Bishkek")
            local = now.astimezone(tz)
            cut = _day_cut(local)
            for s in CashShift.all_clinics.filter(branch=b, status=CashShift.STATUS_OPEN, opened_at__lt=cut):
                close_shift(s, now=now)
                done["closed"] += 1
                say("закрыта смена %s / %s" % (clinic.name, b.name))
            if local.time() < OPEN_AT:
                continue   # ночью и до 08:00 смену сами не открываем
            if CashShift.all_clinics.filter(branch=b).filter(opened_at__gte=cut).exists() or \
                    CashShift.all_clinics.filter(branch=b, status=CashShift.STATUS_OPEN).exists():
                continue
            last = CashShift.all_clinics.filter(branch=b).order_by("-opened_at").first()
            opener = last.opened_by if last else None
            if opener is None:
                continue
            try:
                CashShift.all_clinics.create(branch=b, clinic=clinic, opened_by=opener, opening_cash=0)
            except IntegrityError:
                continue
            done["opened"] += 1
            say("открыта смена %s / %s" % (clinic.name, b.name))
    return done

