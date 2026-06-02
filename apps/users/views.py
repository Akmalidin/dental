from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from .forms import LoginForm, UserForm, BranchForm
from .models import User, Branch, Role
from .decorators import role_required


@login_required
def superadmin_panel(request):
    if not request.user.is_superadmin:
        messages.error(request, _("Доступ только для суперадмина"))
        return redirect("dashboard")
    from apps.services.models import Service, ServiceCategory
    from apps.warehouse.models import Product

    from apps.settings_clinic.models import ClinicSettings
    clinic = ClinicSettings.get()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_modules":
            clinic.enabled_modules = request.POST.getlist("modules")
            clinic.tariff_plan = request.POST.get("tariff_plan", "full")
            clinic.save(update_fields=["enabled_modules", "tariff_plan"])
            messages.success(request, _("Доступные модули обновлены"))
            return redirect("superadmin_panel")
        if action == "create_branch":
            name = request.POST.get("name", "").strip()
            if name:
                Branch.objects.create(
                    name=name,
                    address=request.POST.get("address", ""),
                    phone=request.POST.get("phone", ""),
                    is_main=bool(request.POST.get("is_main")),
                )
                messages.success(request, _("Клиника/филиал «%(n)s» создан") % {"n": name})
            return redirect("superadmin_panel")
        elif action == "create_user":
            login_val = request.POST.get("login", "").strip()
            name = request.POST.get("name", "").strip()
            password = request.POST.get("password", "").strip()
            role_id = request.POST.get("role")
            branch_id = request.POST.get("branch")
            if login_val and name and password:
                if User.objects.filter(login=login_val).exists():
                    messages.error(request, _("Логин уже занят"))
                else:
                    user = User.objects.create(
                        login=login_val, name=name,
                        email=request.POST.get("email", ""),
                        role_id=role_id or None,
                    )
                    user.set_password(password)
                    user.save()
                    if branch_id:
                        user.branches.add(branch_id)
                    messages.success(request, _("Сотрудник «%(n)s» создан") % {"n": name})
            else:
                messages.error(request, _("Заполните логин, имя и пароль"))
            return redirect("superadmin_panel")

    return render(request, "users/superadmin.html", {
        "services_count": Service.objects.count(),
        "service_cats_count": ServiceCategory.objects.count(),
        "materials_count": Product.objects.count(),
        "branches": Branch.objects.all(),
        "staff": User.objects.select_related("role").filter(is_active=True),
        "roles": Role.objects.all(),
        "all_modules": ClinicSettings.ALL_MODULES,
        "enabled_modules": clinic.enabled_modules or [m[0] for m in ClinicSettings.ALL_MODULES],
        "tariff_plan": clinic.tariff_plan,
    })


@login_required
@require_POST
def seed_dental_view(request):
    if not request.user.is_superadmin:
        messages.error(request, _("Доступ только для суперадмина"))
        return redirect("dashboard")
    from apps.services.seed_data import seed_dental
    result = seed_dental()
    messages.success(request, _(
        "Готово! Услуг %(s)s, материалов %(m)s, шаблонов ЭМК %(e)s, документов %(d)s"
    ) % {"s": result["services"], "m": result["materials"],
         "e": result.get("emr", 0), "d": result.get("docs", 0)})
    return redirect("superadmin_panel")


@login_required
def profile_view(request):
    from django.contrib.auth import update_session_auth_hash
    user = request.user
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        login_val = request.POST.get("login", "").strip()
        password = request.POST.get("password", "").strip()
        password2 = request.POST.get("password2", "").strip()
        avatar = request.FILES.get("avatar")
        errors = []
        if name:
            user.name = name
        if login_val and login_val != user.login:
            if user.__class__.objects.filter(login=login_val).exclude(pk=user.pk).exists():
                errors.append(_("Этот логин уже занят"))
            else:
                user.login = login_val
        if avatar:
            user.avatar = avatar
        if password:
            if password != password2:
                errors.append(_("Пароли не совпадают"))
            elif len(password) < 6:
                errors.append(_("Пароль слишком короткий (минимум 6 символов)"))
            else:
                user.set_password(password)
                update_session_auth_hash(request, user)
        if not errors:
            user.save()
            messages.success(request, _("Профиль обновлён"))
            return redirect("profile")
        for e in errors:
            messages.error(request, e)
    return render(request, "users/profile.html", {"profile_user": user})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("/")
    form = LoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        next_url = request.GET.get("next", "/")
        return redirect(next_url)
    return render(request, "auth/login.html", {"form": form})


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect("/login/")


@login_required
def dashboard_view(request):
    from datetime import date
    from django.db.models import Sum, Count
    from decimal import Decimal
    user = request.user
    context = {"user": user}

    if user.is_doctor:
        from apps.appointments.models import Appointment
        from apps.patients.models import Patient
        from apps.tasks.models import Task
        today = date.today()
        context.update({
            "my_appointments_today": Appointment.objects.filter(doctor=user, start_at__date=today).count(),
            "upcoming_appointments": Appointment.objects.filter(
                doctor=user, start_at__date__gte=today,
                status__in=["scheduled", "confirmed"]
            ).select_related("patient", "service").order_by("start_at")[:10],
            "my_patients_count": Patient.objects.filter(
                treatments__doctor=user
            ).distinct().count(),
            "my_tasks_count": Task.objects.filter(
                assigned_to=user, status__in=["pending", "in_progress"]
            ).count(),
            "followups_count": 0,
        })
        template = "dashboard/doctor.html"

    elif user.is_admin or user.is_superadmin:
        import json as _json
        from datetime import datetime
        from apps.appointments.models import Appointment
        from apps.patients.models import Patient
        from apps.finance.models import Payment, Expense
        from apps.treatments.models import Treatment
        today = date.today()
        year_start = today.replace(month=1, day=1)
        income_today = Payment.objects.filter(
            created_at__date=today, type="income"
        ).aggregate(s=Sum("amount"))["s"] or Decimal(0)

        # Monthly appointment stats (bar chart): scheduled vs cancelled
        months_ru = ["Янв","Фев","Мар","Апр","Май","Июн","Июл","Авг","Сен","Окт","Ноя","Дек"]
        appt_per_month = [0] * 12
        cancel_per_month = [0] * 12
        for a in Appointment.objects.filter(start_at__date__gte=year_start):
            m = a.start_at.month - 1
            if a.status == "cancelled":
                cancel_per_month[m] += 1
            else:
                appt_per_month[m] += 1

        context.update({
            "today_appointments_list": Appointment.objects.filter(
                start_at__date=today
            ).select_related("patient", "doctor").order_by("start_at")[:15],
            "registered_patients": Patient.objects.count(),
            "scheduled_visits": Appointment.objects.filter(status__in=["scheduled", "confirmed"]).count(),
            "completed_visits": Appointment.objects.filter(status="completed").count(),
            "cancelled_visits": Appointment.objects.filter(status="cancelled").count(),
            "today_appointments": Appointment.objects.filter(start_at__date=today).count(),
            "new_patients": Patient.objects.filter(created_at__date__gte=today).count(),
            "income_today": income_today,
            "debtors_count": Patient.objects.filter(balance__lt=0).count(),
            "top_debtors": Patient.objects.filter(balance__lt=0).order_by("balance")[:5],
            "recent_payments": Payment.objects.select_related("patient").order_by("-created_at")[:6],
            "upcoming_treatments": Treatment.objects.select_related("patient", "doctor")
                .filter(status__in=["planned", "in_progress"]).order_by("-created_at")[:6],
            "chart_months": months_ru,
            "chart_appts": appt_per_month,
            "chart_cancels": cancel_per_month,
        })
        template = "dashboard/admin.html"

    else:
        template = "dashboard/default.html"

    return render(request, template, context)


# ─── Staff management ────────────────────────────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def staff_list(request):
    users = User.objects.select_related("role").prefetch_related("branches").filter(is_active=True)
    form = UserForm()
    return render(request, "users/list.html", {"users": users, "form": form})


@login_required
@role_required("superadmin", "admin_main")
def staff_create(request):
    form = UserForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        form.save()
        messages.success(request, _("Сотрудник добавлен"))
        return redirect("staff_list")
    return render(request, "users/form.html", {"form": form, "title": _("Добавить сотрудника")})


@login_required
@role_required("superadmin", "admin_main")
def staff_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = UserForm(request.POST or None, request.FILES or None, instance=user)
    if form.is_valid():
        form.save()
        messages.success(request, _("Данные обновлены"))
        return redirect("staff_list")
    return render(request, "users/form.html", {"form": form, "title": _("Редактировать сотрудника"), "object": user})


@login_required
@role_required("superadmin", "admin_main")
def staff_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        user.is_active = False
        user.save()
        messages.success(request, _("Сотрудник деактивирован"))
        return redirect("staff_list")
    return render(request, "users/confirm_delete.html", {"object": user})


# ─── Branch management ───────────────────────────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def branch_list(request):
    branches = Branch.objects.all()
    return render(request, "users/branches.html", {"branches": branches})


@login_required
@role_required("superadmin", "admin_main")
def branch_create(request):
    form = BranchForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, _("Филиал добавлен"))
        return redirect("branch_list")
    return render(request, "users/branch_form.html", {"form": form})


@login_required
@role_required("superadmin", "admin_main")
def branch_edit(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    form = BranchForm(request.POST or None, instance=branch)
    if form.is_valid():
        form.save()
        messages.success(request, _("Филиал обновлён"))
        return redirect("branch_list")
    return render(request, "users/branch_form.html", {"form": form, "object": branch})


# ─── Salary ──────────────────────────────────────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def salary_report(request):
    from datetime import date
    from decimal import Decimal
    from django.db.models import Sum, Q
    from .models_salary import SalaryScheme
    from apps.treatments.models import Treatment
    from apps.finance.models import Payment

    today = date.today()
    month_start = today.replace(day=1)
    period = request.GET.get("period", month_start.isoformat())
    try:
        from datetime import datetime
        p_start = datetime.fromisoformat(period).date().replace(day=1)
    except (ValueError, TypeError):
        p_start = month_start

    doctors = User.objects.filter(role__name="doctor", is_active=True).select_related("role")
    rows = []
    for doc in doctors:
        revenue = Treatment.objects.filter(
            doctor=doc, created_at__date__gte=p_start
        ).aggregate(s=Sum("total_amount"))["s"] or Decimal(0)
        paid = Payment.objects.filter(
            treatment__doctor=doc, type="income", created_at__date__gte=p_start
        ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
        scheme = getattr(doc, "salary_scheme", None)
        salary = Decimal(str(scheme.calculate(float(revenue), float(paid)))) if scheme else Decimal(0)
        rows.append({
            "doctor": doc,
            "scheme": scheme,
            "revenue": revenue,
            "paid": paid,
            "salary": salary,
        })

    total_salary = sum(r["salary"] for r in rows)
    return render(request, "users/salary.html", {
        "rows": rows,
        "period": p_start,
        "total_salary": total_salary,
    })


@login_required
@role_required("superadmin", "admin_main")
def salary_scheme_edit(request, pk):
    from .models_salary import SalaryScheme
    user = get_object_or_404(User, pk=pk)
    scheme, _created = SalaryScheme.objects.get_or_create(user=user)
    if request.method == "POST":
        scheme.scheme_type = request.POST.get("scheme_type", scheme.scheme_type)
        scheme.fixed_amount = request.POST.get("fixed_amount") or 0
        scheme.percent = request.POST.get("percent") or 0
        scheme.description = request.POST.get("description", "")
        scheme.save()
        messages.success(request, _("Схема зарплаты сохранена"))
        return redirect("salary_report")
    return render(request, "users/salary_scheme_form.html", {
        "object": user,
        "scheme": scheme,
        "scheme_types": SalaryScheme.TYPE_CHOICES,
    })


# ─── Doctor schedule ─────────────────────────────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def schedule_list(request):
    from .models_salary import DoctorSchedule
    doctors = User.objects.filter(role__name="doctor", is_active=True).prefetch_related("schedules__branch")
    return render(request, "users/schedule.html", {
        "doctors": doctors,
        "days": DoctorSchedule.DAY_CHOICES,
    })


@login_required
@role_required("superadmin", "admin_main")
def schedule_edit(request, pk):
    from .models_salary import DoctorSchedule
    doctor = get_object_or_404(User, pk=pk)
    branches = Branch.objects.all()
    if request.method == "POST":
        branch_id = request.POST.get("branch")
        branch = Branch.objects.filter(pk=branch_id).first() or branches.first()
        DoctorSchedule.objects.filter(doctor=doctor).delete()
        for day_num, _label in DoctorSchedule.DAY_CHOICES:
            if request.POST.get(f"work_{day_num}"):
                start = request.POST.get(f"start_{day_num}") or "09:00"
                end = request.POST.get(f"end_{day_num}") or "18:00"
                DoctorSchedule.objects.create(
                    doctor=doctor, branch=branch, day_of_week=day_num,
                    start_time=start, end_time=end, is_working=True,
                )
        messages.success(request, _("График сохранён"))
        return redirect("schedule_list")
    existing = {s.day_of_week: s for s in doctor.schedules.all()}
    day_rows = []
    for num, label in DoctorSchedule.DAY_CHOICES:
        s = existing.get(num)
        day_rows.append({
            "num": num,
            "label": label,
            "working": s is not None,
            "start": s.start_time.strftime("%H:%M") if s else "09:00",
            "end": s.end_time.strftime("%H:%M") if s else "18:00",
        })
    return render(request, "users/schedule_form.html", {
        "object": doctor,
        "branches": branches,
        "day_rows": day_rows,
    })
