"""Рассрочка: построение графика и учёт оплат по нему.

Оплаты пациента принимаются как обычно (касса, карточка). Всё, что пациент
заплатил после оформления рассрочки (приходы минус возвраты с
plan.counted_from), засчитывается в платежи графика по порядку сроков:
сначала самый ранний. Так не нужно отдельно отмечать «это платёж по
рассрочке» — достаточно принять деньги.

Статус платежа графика: оплачен / частично / просрочен (срок прошёл, не
покрыт) / ожидается. Рассрочка погашена, когда покрыты все платежи —
тогда статус плана сам становится «Погашена».
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import InstallmentItem, InstallmentPlan, Payment

ZERO = Decimal(0)


def _q(v):
    return Decimal(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def build_schedule(total, down_payment, months, first_due, today=None):
    """[(дата, сумма)]: первый взнос (если есть) — сегодня, остальное — равными
    частями (целые суммы, остаток — в последний платёж) раз в месяц с first_due."""
    today = today or timezone.localdate()
    total, down = Decimal(total), Decimal(down_payment or 0)
    rows = []
    if down > 0:
        rows.append((today, down))
    rest = total - down
    if rest > 0:
        part = _q(rest / months)
        for i in range(months):
            amount = part if i < months - 1 else rest - part * (months - 1)
            rows.append((add_months(first_due, i), amount))
    return rows


@transaction.atomic
def create_plan(patient, total, rows, user=None, note=""):
    plan = InstallmentPlan.objects.create(patient=patient, total=Decimal(total), note=note[:300],
                                          created_by=user, clinic_id=patient.clinic_id)
    InstallmentItem.objects.bulk_create([InstallmentItem(plan=plan, due_date=d, amount=Decimal(a))
                                         for d, a in rows])
    return plan


def paid_since(plan):
    qs = Payment.all_clinics.filter(patient_id=plan.patient_id, created_at__gte=plan.counted_from)
    inc = qs.filter(type=Payment.TYPE_INCOME).aggregate(s=Sum("amount"))["s"] or ZERO
    ref = qs.filter(type=Payment.TYPE_REFUND).aggregate(s=Sum("amount"))["s"] or ZERO
    return max(ZERO, inc - ref)


def state(plan, today=None):
    """Расчёт графика: items со статусами, итоги, ближайший платёж."""
    today = today or timezone.localdate()
    money = paid_since(plan)
    items, paid_total, overdue_sum = [], ZERO, ZERO
    next_item = None
    for it in plan.items.all():
        covered = min(money, it.amount)
        money -= covered
        paid_total += covered
        left = it.amount - covered
        if left <= 0:
            st = "paid"
        elif it.due_date < today:
            st = "overdue"
            overdue_sum += left
        elif covered > 0:
            st = "partial"
        else:
            st = "upcoming"
        if left > 0 and next_item is None:
            next_item = it
        items.append({"id": it.pk, "due": it.due_date, "amount": it.amount, "paid": covered,
                      "left": left, "status": st})
    left_total = sum((i["left"] for i in items), ZERO)
    return {
        "items": items, "paid": paid_total, "left": left_total, "overdue": overdue_sum,
        "next": next_item, "done": bool(items) and left_total <= 0,
    }


def refresh_status(plan):
    """Погашенная рассрочка закрывается сама (и снова открывается, если оплату
    вернули)."""
    if plan.status == InstallmentPlan.STATUS_CANCELLED:
        return plan.status
    s = state(plan)
    new = InstallmentPlan.STATUS_DONE if s["done"] else InstallmentPlan.STATUS_ACTIVE
    if new != plan.status:
        plan.status = new
        plan.save(update_fields=["status", "updated_at"])
    return new


STATUS_LABEL = {"paid": "Оплачен", "partial": "Частично", "overdue": "Просрочен", "upcoming": "Ожидается"}


def plan_json(plan, today=None):
    s = state(plan, today)
    f = float
    return {
        "id": plan.pk, "patientId": plan.patient_id,
        "patient": plan.patient.full_name if plan.patient_id else "", "phone": plan.patient.phone or "",
        "total": f(plan.total), "paid": f(s["paid"]), "left": f(s["left"]), "overdue": f(s["overdue"]),
        "status": plan.status, "statusLabel": plan.get_status_display(), "note": plan.note,
        "created": timezone.localtime(plan.created_at).strftime("%d.%m.%Y"),
        "nextDue": s["next"].due_date.strftime("%d.%m.%Y") if s["next"] else "",
        "nextAmount": f(next((i["left"] for i in s["items"] if i["left"] > 0), ZERO)),
        "items": [{"id": i["id"], "due": i["due"].strftime("%d.%m.%Y"), "dueIso": i["due"].isoformat(),
                   "amount": f(i["amount"]), "paid": f(i["paid"]), "left": f(i["left"]),
                   "status": i["status"], "statusLabel": STATUS_LABEL[i["status"]]} for i in s["items"]],
    }


def reminder_text(plan, item, overdue=False):
    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()
    name = plan.patient.first_name or plan.patient.full_name
    cur = getattr(cs, "currency_label", "сом")
    amount = f"{int(item['left']):,}".replace(",", " ")
    if overdue:
        return (f"Здравствуйте, {name}! Это {cs.name}.\n\nПо рассрочке был платёж *{amount} {cur}* "
                f"до {item['due']:%d.%m.%Y} — он пока не поступил. Пожалуйста, оплатите в клинике "
                f"или напишите нам, если нужно перенести срок.")
    return (f"Здравствуйте, {name}! Это {cs.name}.\n\nНапоминаем: завтра, {item['due']:%d.%m.%Y}, "
            f"платёж по рассрочке — *{amount} {cur}*. Спасибо!")


def send_to_patient(patient, msg):
    """Основной мессенджер клиники, при неудаче — второй; сохраняется в переписке."""
    from apps.notifications.models import WaMessage
    from apps.notifications.telegram import tg_enabled, tg_send_text
    from apps.notifications.whatsapp import wa_enabled, wa_send_text
    from apps.settings_clinic.models import ClinicSettings

    def via_wa():
        if not (patient.phone and wa_enabled()):
            return False
        ok = wa_send_text(patient.phone, msg)
        WaMessage.objects.create(patient=patient, direction="out", channel="wa", phone=patient.phone, body=msg, ok=ok)
        return ok

    def via_tg():
        if not (patient.telegram_chat_id and tg_enabled()):
            return False
        ok = tg_send_text(patient.telegram_chat_id, msg.replace("*", ""))
        WaMessage.objects.create(patient=patient, direction="out", channel="tg",
                                 phone=str(patient.telegram_chat_id), body=msg, ok=ok)
        return ok

    first, second = (via_tg, via_wa) if getattr(ClinicSettings.get(), "primary_messenger", "") == "tg" \
        else (via_wa, via_tg)
    return first() or second()


REMINDER_DEFAULTS = {
    "enabled": True,
    "before_days": [1],      # за сколько дней до срока (0 — в день платежа)
    "hour": 10,              # во сколько по времени клиники
    "overdue_after": 2,      # первое напоминание о просрочке — через N дней (0 — не напоминать)
    "overdue_repeat": 0,     # повторять каждые N дней (0 — один раз)
    "overdue_max": 3,        # не больше N напоминаний о просрочке
}
BEFORE_CHOICES = (7, 3, 1, 0)


def reminder_settings(cs=None):
    """Настройки клиники поверх значений по умолчанию, с проверкой границ."""
    if cs is None:
        from apps.settings_clinic.models import ClinicSettings
        cs = ClinicSettings.get()
    raw = dict(REMINDER_DEFAULTS)
    raw.update({k: v for k, v in (getattr(cs, "installment_reminders", None) or {}).items() if k in REMINDER_DEFAULTS})
    return clean_settings(raw)


def clean_settings(raw):
    def num(v, lo, hi, default):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return default
    d = REMINDER_DEFAULTS
    before = raw.get("before_days", d["before_days"])
    if not isinstance(before, (list, tuple)):
        before = [before]
    before = sorted({num(b, 0, 30, -1) for b in before} & set(BEFORE_CHOICES), reverse=True)
    return {
        "enabled": bool(raw.get("enabled", d["enabled"])),
        "before_days": before,
        "hour": num(raw.get("hour"), 6, 22, d["hour"]),
        "overdue_after": num(raw.get("overdue_after"), 0, 60, d["overdue_after"]),
        "overdue_repeat": num(raw.get("overdue_repeat"), 0, 60, d["overdue_repeat"]),
        "overdue_max": num(raw.get("overdue_max"), 1, 12, d["overdue_max"]),
    }


def _before_text(plan, item, days):
    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()
    name = plan.patient.first_name or plan.patient.full_name
    cur = getattr(cs, "currency_label", "сом")
    amount = f"{int(item['left']):,}".replace(",", " ")
    when = {0: "сегодня", 1: "завтра"}.get(days, f"через {days} дн.")
    return (f"Здравствуйте, {name}! Это {cs.name}.\n\nНапоминаем: {when}, {item['due']:%d.%m.%Y}, "
            f"платёж по рассрочке — *{amount} {cur}*. Спасибо!")


def run_reminders(now=None, log=None, force_hour=False):
    """Напоминания по настройкам клиники (reminder_settings): за выбранные дни
    до срока и после просрочки (с повтором). Запускается каждый час (cron),
    отправляет в выбранный час по времени клиники; каждое напоминание — один
    раз (журнал InstallmentItem.reminder_log)."""
    from datetime import timedelta
    from apps.tenancy import clear_current_clinic, set_current_clinic
    from apps.users.models import Clinic
    say = log or (lambda *_: None)
    sent = 0
    now = now or timezone.now()
    for clinic in Clinic.objects.filter(is_active=True):
        set_current_clinic(clinic)
        try:
            cfg = reminder_settings()
            local = timezone.localtime(now)
            if not cfg["enabled"] or (not force_hour and local.hour != cfg["hour"]):
                continue
            day = local.date()
            for plan in (InstallmentPlan.all_clinics.filter(clinic=clinic, status=InstallmentPlan.STATUS_ACTIVE)
                         .select_related("patient")):
                if refresh_status(plan) != InstallmentPlan.STATUS_ACTIVE:
                    continue
                s = state(plan, day)
                objs = {o.pk: o for o in plan.items.all()}
                for i in s["items"]:
                    if i["left"] <= 0:
                        continue
                    obj = objs[i["id"]]
                    rl = dict(obj.reminder_log or {})
                    msg = None
                    days_left = (i["due"] - day).days
                    if days_left >= 0:
                        if days_left in cfg["before_days"] and days_left not in rl.get("before", []):
                            msg = _before_text(plan, i, days_left)
                            rl["before"] = sorted(set(rl.get("before", [])) | {days_left}, reverse=True)
                    elif cfg["overdue_after"]:
                        late = -days_left
                        count = rl.get("overdue", 0)
                        last = rl.get("overdue_last")
                        due_now = False
                        if count == 0:
                            due_now = late >= cfg["overdue_after"]
                        elif cfg["overdue_repeat"] and count < cfg["overdue_max"] and last:
                            due_now = (day - date.fromisoformat(last)).days >= cfg["overdue_repeat"]
                        if due_now and count < cfg["overdue_max"]:
                            msg = reminder_text(plan, i, overdue=True)
                            rl["overdue"] = count + 1
                            rl["overdue_last"] = day.isoformat()
                    if msg:
                        if send_to_patient(plan.patient, msg):
                            sent += 1
                        obj.reminder_log = rl
                        obj.save(update_fields=["reminder_log"])
                        say(f"{plan.patient.full_name}: {i['due']} ({'до срока' if days_left >= 0 else 'просрочка'})")
        finally:
            clear_current_clinic()
    return sent
