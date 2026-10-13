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


OVERDUE_REMIND_AFTER_DAYS = 2


def run_reminders(today=None, log=None):
    """Напоминания: за день до срока и через OVERDUE_REMIND_AFTER_DAYS дня после
    просрочки (каждое — один раз на платёж). По каждой клинике — со своими
    настройками и мессенджерами."""
    from datetime import timedelta
    from apps.tenancy import clear_current_clinic, set_current_clinic
    from apps.users.models import Clinic
    say = log or (lambda *_: None)
    sent = 0
    for clinic in Clinic.objects.filter(is_active=True):
        set_current_clinic(clinic)
        try:
            day = today or timezone.localdate()
            for plan in (InstallmentPlan.all_clinics.filter(clinic=clinic, status=InstallmentPlan.STATUS_ACTIVE)
                         .select_related("patient")):
                if refresh_status(plan) != InstallmentPlan.STATUS_ACTIVE:
                    continue
                s = state(plan, day)
                objs = {o.pk: o for o in plan.items.all()}
                for i in s["items"]:
                    obj = objs[i["id"]]
                    if i["left"] <= 0:
                        continue
                    if i["due"] == day + timedelta(days=1) and not obj.reminded_before:
                        if send_to_patient(plan.patient, reminder_text(plan, i)):
                            sent += 1
                        obj.reminded_before = True
                        obj.save(update_fields=["reminded_before"])
                        say(f"напомнили: {plan.patient.full_name} {i['due']}")
                    elif i["status"] == "overdue" and not obj.reminded_overdue and \
                            (day - i["due"]).days >= OVERDUE_REMIND_AFTER_DAYS:
                        if send_to_patient(plan.patient, reminder_text(plan, i, overdue=True)):
                            sent += 1
                        obj.reminded_overdue = True
                        obj.save(update_fields=["reminded_overdue"])
                        say(f"просрочка: {plan.patient.full_name} {i['due']}")
        finally:
            clear_current_clinic()
    return sent
