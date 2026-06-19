from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from .models import Payment, Expense, ExpenseCategory, PatientAdvance
from .forms import PaymentForm, ExpenseForm
from apps.patients.models import Patient


@login_required
def finance_dashboard(request):
    today = date.today()
    month_start = today.replace(day=1)
    income_today = Payment.objects.filter(
        created_at__date=today, type="income"
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    income_month = Payment.objects.filter(
        created_at__date__gte=month_start, type="income"
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    expenses_month = Expense.objects.filter(date__gte=month_start).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    top_debtors = Patient.objects.filter(balance__lt=0).order_by("balance")[:5]
    return render(request, "finance/dashboard.html", {
        "income_today": income_today,
        "income_month": income_month,
        "expenses_month": expenses_month,
        "net_month": income_month - expenses_month,
        "top_debtors": top_debtors,
    })


@login_required
def payment_list(request):
    payments = Payment.objects.select_related("patient", "received_by", "treatment").order_by("-created_at")
    form = PaymentForm()
    return render(request, "finance/payments.html", {"payments": payments, "form": form})


def _recalc_patient_balance(patient):
    """Пересчёт баланса пациента по платежам и долгам приёмов."""
    if not patient:
        return
    income = Payment.objects.filter(patient=patient, type="income").aggregate(s=Sum("amount"))["s"] or Decimal(0)
    refunds = Payment.objects.filter(patient=patient, type="refund").aggregate(s=Sum("amount"))["s"] or Decimal(0)
    total_debt = sum(t.debt for t in patient.treatments.all())
    patient.balance = income - refunds - total_debt
    patient.save(update_fields=["balance"])


def _notify_cashier_payment(request, payment):
    """Уведомить администраторов клиники о принятой оплате."""
    if payment.type != "income":
        return
    from apps.notifications.models import Notification
    from apps.users.models import clinic_staff
    from apps.tenancy import get_current_clinic
    u = request.user
    if getattr(u, "is_doctor", False):
        receiver = _("врач %(n)s") % {"n": u.name}
    else:
        receiver = _("администратор %(n)s") % {"n": u.name}
    patient_name = payment.patient.full_name if payment.patient else "—"
    title = _("Оплата принята")
    body = _("%(amount)s сом от %(patient)s. Метод: %(method)s. Принял: %(receiver)s.") % {
        "amount": f"{payment.amount:.0f}", "patient": patient_name,
        "method": payment.get_method_display(), "receiver": receiver,
    }
    admins = (clinic_staff(get_current_clinic())
              .filter(role__name__in=["superadmin", "admin_main", "admin"]))
    seen = set()
    for admin in admins:
        if admin.pk in seen:
            continue
        seen.add(admin.pk)
        Notification.send(user=admin, title=title, body=body, type="payment",
                          link="/finance/payments/", actor=u)


@login_required
def payment_receipt(request, pk):
    """Печатный чек платежа. ?w=80 — формат 80мм для ККМ (термопринтер)."""
    payment = get_object_or_404(
        Payment.objects.select_related("patient", "received_by", "treatment", "branch"), pk=pk)
    from apps.settings_clinic.models import ClinicSettings
    return render(request, "finance/payment_receipt.html", {
        "payment": payment, "clinic_settings": ClinicSettings.get(),
        "w80": request.GET.get("w") == "80",
    })


@login_required
def payment_edit(request, pk):
    """Изменить платёж + пересчитать баланс пациента."""
    payment = get_object_or_404(Payment, pk=pk)
    form = PaymentForm(request.POST or None, instance=payment)
    if request.method == "POST" and form.is_valid():
        old_patient = Payment.objects.get(pk=pk).patient
        payment = form.save()
        _recalc_patient_balance(payment.patient)
        if old_patient and old_patient != payment.patient:
            _recalc_patient_balance(old_patient)
        messages.success(request, _("Платёж изменён"))
        return redirect("payment_list")
    return render(request, "finance/payment_form.html", {"form": form, "edit": True, "payment": payment})


@login_required
def payment_create(request):
    patient_id = request.POST.get("patient") or request.GET.get("patient")
    treatment_id = request.POST.get("treatment") or request.GET.get("treatment")
    form = PaymentForm(request.POST or None, initial={
        "patient": patient_id, "treatment": treatment_id
    })
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.received_by = request.user
        if not payment.branch_id:   # по умолчанию — активный/основной филиал
            from apps.users.models import Branch
            payment.branch = (Branch.objects.filter(pk=request.session.get("active_branch")).first()
                              or Branch.objects.filter(is_main=True).first()
                              or request.user.branches.first()
                              or Branch.objects.first())
        payment.save()
        # update patient balance
        _recalc_patient_balance(payment.patient)
        # уведомление администраторам о принятой оплате
        _notify_cashier_payment(request, payment)
        messages.success(request, _("Платёж зафиксирован"))
        if patient_id:
            return redirect("patient_detail", pk=patient_id)
        return redirect("payment_list")
    return render(request, "finance/payment_form.html", {"form": form})


@login_required
def expense_list(request):
    expenses = Expense.objects.select_related("category", "branch", "created_by").order_by("-date")
    return render(request, "finance/expenses.html", {"expenses": expenses, "form": ExpenseForm()})


@login_required
def expense_create(request):
    form = ExpenseForm(request.POST or None)
    if form.is_valid():
        expense = form.save(commit=False)
        expense.created_by = request.user
        expense.save()
        messages.success(request, _("Расход добавлен"))
        return redirect("expense_list")
    return render(request, "finance/expense_form.html", {"form": form})


@login_required
def debtors_list(request):
    debtors = Patient.objects.filter(balance__lt=0).order_by("balance")
    return render(request, "finance/debtors.html", {"debtors": debtors})
