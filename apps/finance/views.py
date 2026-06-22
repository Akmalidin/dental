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
    _pay = payments_visible_to(Payment.objects.all(), request.user)
    income_today = _pay.filter(
        created_at__date=today, type="income"
    ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    income_month = _pay.filter(
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


def payments_visible_to(qs, user):
    """Видимость платежей по роли:
    - суперадмин/директор — все;
    - администратор (кассир) — только кассовые (отправленные/принятые в кассе);
    - врач — только свои."""
    from apps.users.models import Role
    if getattr(user, "is_superadmin", False):
        return qs
    roles = user.all_role_names
    if Role.ADMIN_MAIN in roles:          # директор
        return qs
    if Role.ADMIN in roles:               # администратор-кассир
        return qs.filter(via_cashier=True)
    if Role.DOCTOR in roles:              # врач — только принятые им
        return qs.filter(received_by=user)
    return qs.filter(received_by=user)


@login_required
def payment_list(request):
    payments = Payment.objects.select_related("patient", "received_by", "treatment").order_by("-created_at")
    payments = payments_visible_to(payments, request.user)
    from apps.treatments.models import Treatment
    patient_id = request.GET.get("patient") or ""
    amount = request.GET.get("amount") or ""
    treatment_id = request.GET.get("treatment") or ""
    preselect = None
    initial = {}
    form = PaymentForm()
    if patient_id:
        p = Patient.objects.filter(pk=patient_id).first()
        if p:
            initial["patient"] = p.pk
            if treatment_id:
                initial["treatment"] = treatment_id
            form = PaymentForm(initial=initial)
            # приёмы только этого пациента
            form.fields["treatment"].queryset = Treatment.objects.filter(patient=p).order_by("-created_at")
            preselect = {"id": p.pk, "name": p.full_name, "amount": amount, "treatment": treatment_id}

    # карта приёмов по пациентам для динамической фильтрации в модале
    treatments_json = {}
    for t in Treatment.objects.exclude(status="cancelled").select_related("patient")[:1000]:
        treatments_json.setdefault(str(t.patient_id), []).append({
            "id": t.pk,
            "label": f"#{t.pk} · {t.created_at:%d.%m.%Y} · долг {t.debt:.0f} сом",
        })
    return render(request, "finance/payments.html", {
        "payments": payments, "form": form, "preselect": preselect,
        "treatments_json": treatments_json,
    })


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


def _qr_svg(data):
    """Inline-SVG QR-код (без Pillow). Возвращает строку <svg…> или ''."""
    try:
        import io, qrcode, qrcode.image.svg
        img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        buf = io.BytesIO(); img.save(buf)
        svg = buf.getvalue().decode()
        return svg[svg.find("<svg"):]  # отрезаем XML-декларацию
    except Exception:
        return ""


@login_required
def payment_receipt(request, pk):
    """Печатный чек платежа. ?w=80 — формат 80мм для ККМ (термопринтер)."""
    payment = get_object_or_404(
        Payment.objects.select_related("patient", "received_by", "treatment", "branch"), pk=pk)
    from apps.settings_clinic.models import ClinicSettings
    public_url = request.build_absolute_uri(f"/r/{payment.public_token}/")
    return render(request, "finance/payment_receipt.html", {
        "payment": payment, "clinic_settings": ClinicSettings.get(),
        "w80": request.GET.get("w") == "80",
        "public_url": public_url, "qr_svg": _qr_svg(public_url),
    })


def payment_public(request, token):
    """Публичная страница чека (по QR, без логина): услуги+цены, пациент, врач,
    файлы/снимки/рентген, зубная формула."""
    payment = get_object_or_404(
        Payment._base_manager.select_related("patient", "received_by", "treatment", "treatment__doctor", "branch", "clinic"),
        public_token=token)
    treatment = payment.treatment
    patient = payment.patient
    cures, files = [], []
    if treatment:
        cures = list(treatment.cures.select_related("service", "doctor").all())
        files = list(treatment.files.all())
    for f in files:
        try:
            f.abs_url = request.build_absolute_uri(f.file.url)
        except Exception:
            f.abs_url = ""

    # Зубная формула пациента (FDI): верхний и нижний ряд + цвет/название статуса
    tooth_map = {}
    if patient:
        from apps.treatments.models_teeth import ToothCondition
        for tc in ToothCondition.objects.filter(patient=patient).select_related("status"):
            tooth_map[tc.tooth_number] = tc
    upper = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
    lower = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
    formula_upper = [(n, tooth_map.get(n)) for n in upper]
    formula_lower = [(n, tooth_map.get(n)) for n in lower]
    has_formula = bool(tooth_map)
    _seen = {}
    for tc in tooth_map.values():
        if tc.status:
            _seen[tc.status_id] = {"name": tc.status.name, "color": tc.status.color}
    tooth_legend = list(_seen.values())

    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()
    return render(request, "finance/receipt_public.html", {
        "payment": payment, "treatment": treatment, "patient": patient,
        "cures": cures, "files": files,
        "formula_upper": formula_upper, "formula_lower": formula_lower,
        "has_formula": has_formula, "tooth_legend": tooth_legend,
        "clinic": getattr(payment, "clinic", None), "clinic_settings": cs,
    })


@login_required
def send_to_cashier(request, patient_id):
    """«В кассу»: уведомить администратора/кассира принять оплату и выдать чек.
    Сам платёж здесь НЕ создаётся — врач не принимает оплату через эту кнопку."""
    patient = get_object_or_404(Patient, pk=patient_id)
    from apps.notifications.models import Notification
    from apps.users.models import clinic_staff
    from apps.tenancy import get_current_clinic
    u = request.user
    debt = getattr(patient, "debt", Decimal(0)) or Decimal(0)
    amount = (request.POST.get("amount") or "").strip()
    treatment_id = (request.POST.get("treatment") or "").strip()
    # сумма платежа: указанная врачом, иначе весь долг
    sum_str = amount if amount else f"{debt:.0f}"
    # приём, из которого вычесть (для чека)
    tr_part = ""
    link = f"/finance/payments/?patient={patient.pk}"
    if amount:
        link += f"&amount={amount}"
    if treatment_id:
        from apps.treatments.models import Treatment as _T
        t = _T.objects.filter(pk=treatment_id, patient=patient).first()
        if t:
            tr_part = _(" Из приёма №%(t)s.") % {"t": t.pk}
            link += f"&treatment={treatment_id}"
    title = _("Принять оплату в кассе")
    body = _("Пациент %(p)s. К оплате: %(s)s сом (долг %(d)s).%(tr)s Направил: %(u)s. Примите оплату и выдайте чек.") % {
        "p": patient.full_name, "s": sum_str, "d": f"{debt:.0f}", "tr": tr_part, "u": u.name,
    }
    admins = (clinic_staff(get_current_clinic())
              .filter(role__name__in=["superadmin", "admin_main", "admin"]))
    sent = 0
    for admin in admins:
        Notification.send(user=admin, title=title, body=body, type="payment",
                          link=link, actor=u)
        sent += 1
    if sent:
        messages.success(request, _("Отправлено в кассу — администратор примет оплату и выдаст чек"))
    else:
        messages.warning(request, _("В клинике нет администратора-кассира для приёма оплаты"))
    return redirect("patient_detail", pk=patient_id)


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
    if payment.patient_id:
        from apps.treatments.models import Treatment
        form.fields["treatment"].queryset = Treatment.objects.filter(patient_id=payment.patient_id).order_by("-created_at")
    return render(request, "finance/payment_form.html", {
        "form": form, "edit": True, "payment": payment, "treatments_json": _treatments_by_patient(),
    })


@login_required
def payment_create(request):
    from apps.treatments.models import Treatment
    patient_id = request.POST.get("patient") or request.GET.get("patient")
    treatment_id = request.POST.get("treatment") or request.GET.get("treatment")
    form = PaymentForm(request.POST or None, initial={
        "patient": patient_id, "treatment": treatment_id
    })
    # показывать в выпадающем списке только приёмы выбранного пациента
    if patient_id:
        form.fields["treatment"].queryset = Treatment.objects.filter(patient_id=patient_id).order_by("-created_at")
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.received_by = request.user
        # Канал: касса (channel=cashier) или врач напрямую. Если не указан — определяем по роли.
        channel = request.POST.get("channel", "")
        if channel == "cashier":
            payment.via_cashier = True
        elif channel == "doctor":
            payment.via_cashier = False
        else:
            payment.via_cashier = not getattr(request.user, "is_doctor", False)
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
    return render(request, "finance/payment_form.html", {
        "form": form, "treatments_json": _treatments_by_patient(),
    })


def _treatments_by_patient():
    """Карта приёмов по пациентам для динамической фильтрации в форме платежа."""
    from apps.treatments.models import Treatment
    data = {}
    for t in Treatment.objects.exclude(status="cancelled").select_related("patient")[:2000]:
        data.setdefault(str(t.patient_id), []).append({
            "id": t.pk, "label": f"#{t.pk} · {t.created_at:%d.%m.%Y} · долг {t.debt:.0f} сом",
        })
    return data


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
