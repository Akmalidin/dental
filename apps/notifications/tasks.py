from celery import shared_task
from django.utils import timezone
from datetime import timedelta


@shared_task(name="apps.notifications.tasks.send_appointment_reminders")
def send_appointment_reminders():
    """Send Telegram reminders for appointments starting in ~2 hours."""
    from apps.appointments.models import Appointment
    from .utils import send_telegram

    now = timezone.now()
    window_start = now + timedelta(hours=1, minutes=45)
    window_end = now + timedelta(hours=2, minutes=15)

    appointments = Appointment.objects.filter(
        start_at__gte=window_start,
        start_at__lte=window_end,
        status__in=["scheduled", "confirmed"],
    ).select_related("patient", "doctor")

    for appt in appointments:
        if appt.patient and appt.patient.telegram_id_via_user():
            pass  # TODO: link patient to telegram

        if appt.doctor.telegram_id:
            text = (
                f"📅 <b>Напоминание о записи</b>\n"
                f"Пациент: {appt.patient.full_name if appt.patient else '—'}\n"
                f"Время: {appt.start_at:%H:%M}\n"
                f"Услуга: {appt.service.name if appt.service else '—'}"
            )
            send_telegram(appt.doctor.telegram_id, text)


@shared_task(name="apps.notifications.tasks.send_daily_admin_report")
def send_daily_admin_report():
    """Daily summary sent to admins at 20:00."""
    from datetime import date
    from django.db.models import Sum
    from decimal import Decimal
    from apps.finance.models import Payment, Expense
    from apps.appointments.models import Appointment
    from .utils import notify_admins

    today = date.today()
    income = Payment.objects.filter(created_at__date=today, type="income").aggregate(s=Sum("amount"))["s"] or Decimal(0)
    refunds = Payment.objects.filter(created_at__date=today, type="refund").aggregate(s=Sum("amount"))["s"] or Decimal(0)
    expenses = Expense.objects.filter(date=today).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    appointments_count = Appointment.objects.filter(start_at__date=today).count()
    completed = Appointment.objects.filter(start_at__date=today, status="completed").count()

    text = (
        f"📊 <b>Отчёт за {today:%d.%m.%Y}</b>\n\n"
        f"💰 Выручка: {income} сом\n"
        f"↩️ Возвраты: {refunds} сом\n"
        f"🧾 Расходы: {expenses} сом\n"
        f"📈 Чистая прибыль: {income - refunds - expenses} сом\n\n"
        f"🗓 Записей: {appointments_count} (завершено: {completed})"
    )
    notify_admins(text)
