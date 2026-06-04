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

    from apps.users.models import Clinic
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_clinic":
            from apps.tenancy import set_current_clinic, clear_current_clinic
            from apps.services.seed_data import seed_dental
            from django.utils.text import slugify
            cname = request.POST.get("clinic_name", "").strip()
            alogin = request.POST.get("clinic_admin_login", "").strip()
            apass = request.POST.get("clinic_admin_password", "").strip()
            if not (cname and alogin and apass):
                messages.error(request, _("Заполните название клиники, логин и пароль администратора"))
                return redirect("superadmin_panel")
            if User.objects.filter(login=alogin).exists():
                messages.error(request, _("Логин администратора уже занят"))
                return redirect("superadmin_panel")
            base = slugify(cname) or "clinic"
            slug, i = base, 2
            while Clinic.objects.filter(slug=slug).exists():
                slug, i = f"{base}-{i}", i + 1
            new_clinic = Clinic.objects.create(name=cname, slug=slug)
            amrole, _r = Role.objects.get_or_create(name=Role.ADMIN_MAIN)
            au = User.objects.create(
                login=alogin, name=request.POST.get("clinic_admin_name") or f"Админ {cname}",
                role=amrole, clinic=new_clinic, is_staff=False,
            )
            au.set_password(apass)
            au.save()
            # филиал + автозаполнение услуг/материалов/ЭМК/документов в новой клинике
            set_current_clinic(new_clinic)
            try:
                Branch.objects.create(name=cname, address="—", phone="—", is_main=True)
                res = seed_dental()
            finally:
                clear_current_clinic()
            messages.success(request, _(
                "Клиника «%(n)s» создана. Админ: %(l)s. Заполнено: услуг %(s)s, материалов %(m)s, ЭМК %(e)s, документов %(d)s"
            ) % {"n": cname, "l": alogin, "s": res["services"], "m": res["materials"],
                 "e": res.get("emr", 0), "d": res.get("docs", 0)})
            return redirect("superadmin_panel")
        if action == "save_modules":
            from apps.tenancy import get_current_clinic
            target = get_current_clinic()
            if target is None:
                messages.error(request, _("Сначала выберите клинику (кнопка «Войти →»), затем настройте тариф"))
                return redirect("superadmin_panel")
            target.enabled_modules = request.POST.getlist("modules")
            target.tariff_plan = request.POST.get("tariff_plan", "standard")
            until = request.POST.get("tariff_until", "").strip()
            if until:
                from datetime import datetime
                try:
                    target.tariff_until = datetime.strptime(until, "%Y-%m-%d").date()
                except ValueError:
                    pass
            else:
                target.tariff_until = None
            target.save(update_fields=["enabled_modules", "tariff_plan", "tariff_until"])
            messages.success(request, _("Тариф клиники «%(n)s» обновлён") % {"n": target.name})
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

    from apps.tenancy import get_current_clinic
    target = get_current_clinic()  # клиника, которую сейчас настраиваем (активная)
    all_keys = [m[0] for m in ClinicSettings.ALL_MODULES]
    return render(request, "users/superadmin.html", {
        "services_count": Service.objects.count(),
        "service_cats_count": ServiceCategory.objects.count(),
        "materials_count": Product.objects.count(),
        "branches": Branch.objects.all(),
        "staff": User.objects.select_related("role").filter(is_active=True),
        "roles": Role.objects.all(),
        "all_modules": ClinicSettings.ALL_MODULES,
        "enabled_modules": (target.enabled_modules or all_keys) if target else all_keys,
        "tariff_plan": target.tariff_plan if target else "",
        "tariff_choices": ClinicSettings.TARIFF_CHOICES,
        "tariff_presets_json": ClinicSettings.TARIFF_PRESETS,
        "target_clinic": target,
        "clinics": Clinic.objects.all(),
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
@require_POST
def set_active_clinic(request):
    """Суперадмин выбирает клинику для работы (или 'все')."""
    if not request.user.is_superadmin:
        return redirect("dashboard")
    cid = request.POST.get("clinic")
    if cid in (None, "", "all"):
        request.session.pop("active_clinic", None)
    else:
        try:
            request.session["active_clinic"] = int(cid)
            request.session.pop("active_branch", None)  # сбросить филиал при смене клиники
        except (TypeError, ValueError):
            pass
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "dashboard")


@login_required
@require_POST
def set_active_branch(request):
    """Переключатель филиала в navbar — сохраняет выбор в сессии."""
    bid = request.POST.get("branch")
    if bid in (None, "", "all"):
        request.session.pop("active_branch", None)
    else:
        try:
            request.session["active_branch"] = int(bid)
        except (TypeError, ValueError):
            pass
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "dashboard")


# ─── Корзина (recycle bin) ───────────────────────────────────────────────────

def _recycle_models():
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    from apps.appointments.models import Appointment
    return {
        "patient": (Patient, "Пациент"),
        "treatment": (Treatment, "Приём"),
        "appointment": (Appointment, "Запись"),
    }


@login_required
@role_required("superadmin", "admin_main", "admin")
def recycle_bin(request):
    items = []
    for kind, (Model, label) in _recycle_models().items():
        for obj in Model.all_objects.filter(is_deleted=True).order_by("-deleted_at")[:200]:
            items.append({
                "kind": kind, "label": label, "pk": obj.pk,
                "title": str(obj), "deleted_at": obj.deleted_at,
                "deleted_by": obj.deleted_by,
            })
    items.sort(key=lambda x: x["deleted_at"] or 0, reverse=True)
    return render(request, "users/recycle_bin.html", {"items": items})


@login_required
@role_required("superadmin", "admin_main", "admin")
@require_POST
def recycle_restore(request, kind, pk):
    models = _recycle_models()
    if kind in models:
        Model = models[kind][0]
        obj = get_object_or_404(Model.all_objects, pk=pk)
        obj.restore()
        messages.success(request, _("Восстановлено: %(t)s") % {"t": str(obj)})
    return redirect("recycle_bin")


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def recycle_purge(request, kind, pk):
    models = _recycle_models()
    if kind in models:
        Model = models[kind][0]
        obj = get_object_or_404(Model.all_objects, pk=pk)
        title = str(obj)
        obj.delete()   # безвозвратно
        messages.success(request, _("Удалено безвозвратно: %(t)s") % {"t": title})
    return redirect("recycle_bin")


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
    from apps.tenancy import get_current_clinic
    users = User.objects.select_related("role").prefetch_related("branches", "roles").filter(is_active=True)
    # изоляция по клинике (User не ClinicScoped — фильтруем явно)
    clinic = get_current_clinic()
    if clinic is not None:
        users = users.filter(clinic=clinic)
    # суперпользователя видит только сам суперпользователь
    if not request.user.is_superadmin:
        users = users.exclude(is_superuser=True).exclude(role__name=Role.SUPERADMIN)
    form = UserForm()
    return render(request, "users/list.html", {"users": users, "form": form})


def _is_protected_target(target, actor):
    """Можно ли actor'у трогать target. Суперпользователя трогает только суперпользователь."""
    if target.is_superadmin and not actor.is_superadmin:
        return True
    return False


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def staff_set_password(request, pk):
    """Сбросить (задать новый) пароль сотруднику. Пароли не показываются — только смена."""
    user = get_object_or_404(User, pk=pk)
    if _is_protected_target(user, request.user):
        messages.error(request, _("Доступ запрещён: нельзя менять пароль суперпользователя"))
        return redirect("staff_list")
    new_pw = request.POST.get("new_password", "").strip()
    if len(new_pw) < 6:
        messages.error(request, _("Пароль слишком короткий (минимум 6 символов)"))
        return redirect("staff_list")
    user.set_password(new_pw)
    user.save(update_fields=["password"])
    messages.success(request, _("Пароль для «%(n)s» изменён. Передайте его сотруднику: %(p)s")
                     % {"n": user.name, "p": new_pw})
    return redirect("staff_list")


@login_required
@role_required("superadmin", "admin_main")
def staff_create(request):
    from apps.tenancy import get_current_clinic
    form = UserForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        new_user = form.save(commit=False)
        # привязать к текущей клинике (или к клинике создателя)
        new_user.clinic = get_current_clinic() or getattr(request.user, "clinic", None)
        new_user.save()
        form.save_m2m()
        messages.success(request, _("Сотрудник добавлен"))
        return redirect("staff_list")
    return render(request, "users/form.html", {"form": form, "title": _("Добавить сотрудника")})


@login_required
@role_required("superadmin", "admin_main")
def staff_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    # защита: суперпользователя редактирует только суперпользователь
    if _is_protected_target(user, request.user):
        messages.error(request, _("Доступ запрещён: нельзя редактировать суперпользователя"))
        return redirect("staff_list")
    form = UserForm(request.POST or None, request.FILES or None, instance=user)
    if form.is_valid():
        # запрет повышения роли до суперадмина не-суперпользователем
        new_role = form.cleaned_data.get("role")
        if (new_role and new_role.name == Role.SUPERADMIN) and not request.user.is_superadmin:
            messages.error(request, _("Доступ запрещён: нельзя назначить роль суперадмина"))
            return redirect("staff_list")
        form.save()
        messages.success(request, _("Данные обновлены"))
        return redirect("staff_list")
    return render(request, "users/form.html", {"form": form, "title": _("Редактировать сотрудника"), "object": user})


@login_required
@role_required("superadmin", "admin_main")
def staff_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if _is_protected_target(user, request.user):
        messages.error(request, _("Доступ запрещён: нельзя удалить суперпользователя"))
        return redirect("staff_list")
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

def _salary_rows(date_from, date_to, completed_only=False):
    """Расчёт зарплат по врачам за период [date_from, date_to]."""
    from decimal import Decimal
    from django.db.models import Sum, Count, Q
    from apps.treatments.models import Treatment
    from apps.finance.models import Payment
    doctors = User.objects.filter(role__name="doctor", is_active=True).select_related("role")
    rows = []
    for doc in doctors:
        t_qs = Treatment.objects.filter(
            doctor=doc, created_at__date__gte=date_from, created_at__date__lte=date_to
        ).exclude(status="cancelled")
        rev_qs = t_qs.filter(status__in=["completed", "paid"]) if completed_only else t_qs
        revenue = rev_qs.aggregate(s=Sum("total_amount"))["s"] or Decimal(0)
        paid = Payment.objects.filter(
            treatment__doctor=doc, type="income",
            created_at__date__gte=date_from, created_at__date__lte=date_to,
        ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
        t_count = t_qs.count()
        c_count = t_qs.filter(status__in=["completed", "paid"]).count()
        avg = (revenue / c_count) if (completed_only and c_count) else ((revenue / t_count) if t_count else Decimal(0))
        scheme = getattr(doc, "salary_scheme", None)
        salary = Decimal(str(scheme.calculate(float(revenue), float(paid)))) if scheme else Decimal(0)
        rows.append({
            "doctor": doc, "scheme": scheme, "revenue": revenue, "paid": paid,
            "treatments_count": t_count, "completed_count": c_count,
            "avg_check": avg, "salary": salary,
        })
    return rows


@login_required
@role_required("superadmin", "admin_main")
def salary_report(request):
    from datetime import date, datetime, timedelta

    today = date.today()
    month_start = today.replace(day=1)
    # диапазон дат: ?from=&to= (по умолчанию текущий месяц)
    def _pd(v, default):
        try:
            return datetime.fromisoformat(v).date()
        except (ValueError, TypeError):
            return default
    date_from = _pd(request.GET.get("from"), month_start)
    date_to = _pd(request.GET.get("to"), today)
    completed_only = request.GET.get("completed") == "1"

    rows = _salary_rows(date_from, date_to, completed_only)
    total_salary = sum(r["salary"] for r in rows)
    total_revenue = sum(r["revenue"] for r in rows)
    total_paid = sum(r["paid"] for r in rows)
    return render(request, "users/salary.html", {
        "rows": rows,
        "period": date_from,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "completed_only": completed_only,
        "total_salary": total_salary,
        "total_revenue": total_revenue,
        "total_paid": total_paid,
    })


@login_required
def my_earnings(request):
    """Заработок текущего врача за день/неделю/месяц/год."""
    from datetime import date, timedelta
    from decimal import Decimal
    from django.db.models import Sum
    from apps.treatments.models import Treatment
    from apps.finance.models import Payment

    doc = request.user
    scheme = getattr(doc, "salary_scheme", None)
    today = date.today()
    periods = [
        ("Сегодня", today),
        ("Неделя", today - timedelta(days=today.weekday())),
        ("Месяц", today.replace(day=1)),
        ("Год", today.replace(month=1, day=1)),
    ]
    cards = []
    for label, start in periods:
        t_qs = Treatment.objects.filter(
            doctor=doc, created_at__date__gte=start, created_at__date__lte=today
        ).exclude(status="cancelled")
        revenue = t_qs.aggregate(s=Sum("total_amount"))["s"] or Decimal(0)
        paid = Payment.objects.filter(
            treatment__doctor=doc, type="income",
            created_at__date__gte=start, created_at__date__lte=today,
        ).aggregate(s=Sum("amount"))["s"] or Decimal(0)
        salary = Decimal(str(scheme.calculate(float(revenue), float(paid)))) if scheme else None
        cards.append({
            "label": label, "revenue": revenue, "paid": paid,
            "count": t_qs.count(), "salary": salary,
        })
    return render(request, "users/my_earnings.html", {
        "cards": cards, "scheme": scheme, "doctor": doc,
    })


@login_required
@role_required("superadmin", "admin_main")
def salary_export(request):
    """Экспорт зарплатной ведомости в Excel."""
    from datetime import date, datetime
    from openpyxl import Workbook
    from django.http import HttpResponse
    today = date.today()
    def _pd(v, default):
        try:
            return datetime.fromisoformat(v).date()
        except (ValueError, TypeError):
            return default
    date_from = _pd(request.GET.get("from"), today.replace(day=1))
    date_to = _pd(request.GET.get("to"), today)
    rows = _salary_rows(date_from, date_to, request.GET.get("completed") == "1")
    wb = Workbook(); ws = wb.active; ws.title = "Зарплата"
    ws.append([f"Зарплатная ведомость {date_from}—{date_to}"])
    ws.append(["Врач", "Схема", "Приёмов", "Завершено", "Выручка", "Оплачено", "Средний чек", "Зарплата"])
    for r in rows:
        ws.append([
            r["doctor"].name,
            r["scheme"].get_scheme_type_display() if r["scheme"] else "—",
            r["treatments_count"], r["completed_count"],
            float(r["revenue"]), float(r["paid"]), float(r["avg_check"]), float(r["salary"]),
        ])
    ws.append([])
    ws.append(["ИТОГО", "", "", "", "", "", "", float(sum(r["salary"] for r in rows))])
    for i, w in enumerate([26, 20, 10, 10, 14, 14, 14, 14], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="salary_{date_from}_{date_to}.xlsx"'
    wb.save(resp)
    return resp


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
