from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from .forms import LoginForm, UserForm, BranchForm
from .models import User, Branch, Role, Permission
from .decorators import role_required, require_permission


def _newui_role_data(clinic):
    """Роли клиники в формате, ожидаемом новым интерфейсом (Персонал → Роли).
    Права даём по 4 реальным категориям каталога (Permission/PermissionCategory);
    у макета изначально было 7 фиктивных флагов (schedule/lab/settings/…),
    которых в реальной системе не существует как отслеживаемых прав."""
    from .roles_views import roles_for_clinic
    color_cycle = ["cobalt", "teal", "amber", "coral", "grey"]
    roles_qs = roles_for_clinic(clinic).order_by("-is_system", "name").prefetch_related("granular_permissions")
    data = []
    for i, role in enumerate(roles_qs):
        codes = set(role.granular_permissions.values_list("code", flat=True))
        categories = set(role.granular_permissions.values_list("category", flat=True))
        data.append({
            "id": role.pk,
            "name": role.display_name,
            "isSystem": role.is_system,
            "color": color_cycle[i % len(color_cycle)],
            "perms": {
                "patients": "patients" in categories,
                "finance": "finance" in categories,
                "staff": "staff" in categories,
                "reports": "reports" in categories,
            },
            "grantedCodes": sorted(codes),
            "staffCount": role.users.count(),
        })
    return data


def _newui_staff_data(request, clinic):
    """Сотрудники клиники для нового интерфейса — те же правила видимости,
    что и в staff_list (скрываем суперпользователя от не-суперадминов)."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.appointments.models import Appointment

    users = User.objects.select_related("role").prefetch_related("branches", "roles")
    users = users.filter(clinic=clinic) if clinic else users
    if not request.user.is_superadmin:
        users = users.exclude(is_superuser=True).exclude(role__name=Role.SUPERADMIN)

    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)
    doctor_ids = [u.pk for u in users if u.is_doctor]
    weekly_counts = {}
    if doctor_ids:
        appt_qs = (Appointment.objects.filter(doctor_id__in=doctor_ids, start_at__date__gte=week_start, start_at__date__lt=week_end)
                   .values_list("doctor_id"))
        for (doc_id,) in appt_qs:
            weekly_counts[doc_id] = weekly_counts.get(doc_id, 0) + 1

    color_by_role = {}
    for i, name in enumerate(Role.objects.filter(clinic__isnull=True).exclude(name=Role.SUPERADMIN).values_list("name", flat=True).order_by("name")):
        color_by_role[name] = ["cobalt", "teal", "amber", "coral", "grey"][i % 5]

    data = []
    for u in users.order_by("name"):
        branch_ids = [b.pk for b in u.branches.all()]
        branch_names = ", ".join(b.name for b in u.branches.all()) or "—"
        load = f"{weekly_counts.get(u.pk, 0)} на неделе" if u.is_doctor else "—"
        data.append({
            "id": u.pk,
            "login": u.login,
            "name": u.name or u.login,
            "email": u.email,
            "roleId": u.role_id,
            "roleName": u.role.display_name if u.role else "",
            "roleColor": color_by_role.get(u.role.name, "grey") if u.role else "grey",
            "extraRoleIds": [r.pk for r in u.roles.all()],
            "extraRoleNames": [r.display_name for r in u.roles.all()],
            "branchIds": branch_ids,
            "branch": branch_names,
            "load": load,
            "phone": u.phone or "",
            "active": u.is_active,
            "color": u.color or "",
            # Персональное ограничение доступа к разделам (allowed_sections=None
            # значит «все разделы») — см. sectionsCatalog/currentUserId в
            # _shared_options и редактор в модалке сотрудника (m-staff).
            "fullAccess": u.allowed_sections is None,
            "allowedSections": list(u.allowed_sections) if u.allowed_sections is not None else [],
        })
    return data


def _newui_dashboard_data():
    """KPI и списки дашборда — только реальные метрики. У макета «Новые заявки»
    и план по выручке опирались на несуществующую в системе CRM-воронку —
    здесь эти карточки заменены на реальные аналоги (новые пациенты, выручка
    вчера вместо плана). Заказы лаборатории — реальные (apps.technicians)."""
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    from datetime import timedelta
    from django.db.models import Sum
    from django.utils import timezone
    from apps.finance.models import Payment
    from apps.appointments.models import Appointment
    from apps.patients.models import Patient
    from apps.technicians.models import TechnicianTask

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    def day_revenue(d):
        income = Payment.objects.filter(created_at__date=d, type=Payment.TYPE_INCOME).aggregate(s=Sum("amount"))["s"] or 0
        refund = Payment.objects.filter(created_at__date=d, type=Payment.TYPE_REFUND).aggregate(s=Sum("amount"))["s"] or 0
        return float(income - refund)

    revenue_today = day_revenue(today)
    revenue_yesterday = day_revenue(yesterday)
    revenue_delta_pct = round((revenue_today - revenue_yesterday) / revenue_yesterday * 100) if revenue_yesterday else None

    week_labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    week_revenue = [day_revenue(week_start + timedelta(days=i)) if week_start + timedelta(days=i) <= today else 0 for i in range(7)]
    max_week_revenue = max(week_revenue) or 1
    week_bars = [
        {"label": week_labels[i], "amount": week_revenue[i], "heightPct": round(week_revenue[i] / max_week_revenue * 100)}
        for i in range(7)
    ]

    patients_today_ids = set(Appointment.objects.filter(start_at__date=today).exclude(patient__isnull=True).values_list("patient_id", flat=True))
    new_patients_today = Patient.objects.filter(created_at__date=today).count()
    new_patients_month = Patient.objects.filter(created_at__date__gte=month_start).count()

    lab_open_qs = TechnicianTask.objects.filter(status__in=TechnicianTask.OPEN_STATUSES)
    lab_open_count = lab_open_qs.count()
    lab_overdue_count = lab_open_qs.filter(expected_ready__lt=today).count()

    upcoming_qs = (Appointment.objects
                   .filter(start_at__date=today, status__in=[Appointment.STATUS_SCHEDULED, Appointment.STATUS_CONFIRMED, Appointment.STATUS_ARRIVED])
                   .select_related("patient", "doctor", "cabinet").order_by("start_at")[:6])
    upcoming = [{
        "patient": a.patient.full_name if a.patient else "Без пациента",
        "service": a.service.name if a.service else "",
        "doctor": a.doctor.name if a.doctor else "",
        "cabinet": a.cabinet.name if a.cabinet else "",
        "time": timezone.localtime(a.start_at).strftime("%H:%M"),
    } for a in upcoming_qs]

    recent_patients = [{
        "name": p.full_name, "phone": p.phone,
        "when": timezone.localtime(p.created_at).strftime("%d.%m %H:%M"),
    } for p in Patient.objects.order_by("-created_at")[:5]]

    return {
        "revenueToday": revenue_today,
        "revenueYesterday": revenue_yesterday,
        "revenueDeltaPct": revenue_delta_pct,
        "patientsToday": len(patients_today_ids),
        "newPatientsToday": new_patients_today,
        "newPatientsMonth": new_patients_month,
        "labOpenCount": lab_open_count,
        "labOverdueCount": lab_overdue_count,
        "weekBars": week_bars,
        "upcoming": upcoming,
        "recentPatients": recent_patients,
        "cashSummary": _dashboard_cash_summary(clinic),
        "doctorsLoad": _dashboard_doctors_load(clinic),
        "funnelNew": _dashboard_funnel_new(clinic),
    }


def _dashboard_cash_summary(clinic):
    """Касса на дашборде: статус текущей смены главного филиала клиники +
    приход/возврат/баланс с момента открытия (та же логика, что
    _newui_cashdesk_data/CashShift.z_report, но сжато для карточки)."""
    from django.utils import timezone
    from apps.finance.models import CashShift
    from apps.users.models import Branch

    closed = {"opened": False, "openedAt": None, "openedBy": None,
              "incomeTotal": 0.0, "refundTotal": 0.0, "balance": 0.0}
    if not clinic:
        return closed

    branch = Branch.objects.filter(clinic=clinic, is_main=True).first() or Branch.objects.filter(clinic=clinic).first()
    shift = CashShift.objects.filter(branch=branch, status=CashShift.STATUS_OPEN).first() if branch else None
    if not shift:
        return closed

    z = shift.z_report()
    return {
        "opened": True,
        "openedAt": timezone.localtime(shift.opened_at).strftime("%d.%m.%Y %H:%M"),
        "openedBy": shift.opened_by.name if shift.opened_by else "—",
        "incomeTotal": float(z["incomeTotal"]),
        "refundTotal": float(z["refundTotal"]),
        "balance": float(z["expectedCash"]),
    }


def _dashboard_minutes_between(start_time, end_time):
    """Разница между двумя datetime.time в минутах (time сам по себе
    вычитать нельзя — комбинируем с фиктивной датой)."""
    import datetime as dt
    start_dt = dt.datetime.combine(dt.date.min, start_time)
    end_dt = dt.datetime.combine(dt.date.min, end_time)
    return int((end_dt - start_dt).total_seconds() // 60)


def _dashboard_doctors_load(clinic):
    """Загрузка врачей сегодня: % занятых минут от рабочего графика
    (apps.users.models_salary.DoctorSchedule). Показываются только врачи,
    у которых есть рабочий график на сегодняшний день недели — отсутствие в
    списке означает выходной, а не 0% загрузки."""
    from django.utils import timezone
    from apps.appointments.models import Appointment
    from apps.users.models import clinic_doctors
    from apps.users.models_salary import DoctorSchedule

    if not clinic:
        return []

    today = timezone.localdate()
    doctors = list(clinic_doctors(clinic))
    doctor_ids = [d.pk for d in doctors]

    available_minutes = {}
    schedules = DoctorSchedule.objects.filter(
        doctor_id__in=doctor_ids, day_of_week=today.weekday(), is_working=True,
    )
    for s in schedules:
        minutes = _dashboard_minutes_between(s.start_time, s.end_time)
        available_minutes[s.doctor_id] = available_minutes.get(s.doctor_id, 0) + minutes

    booked_minutes = {}
    appts = (Appointment.objects
             .filter(doctor_id__in=list(available_minutes.keys()), start_at__date=today)
             .exclude(status=Appointment.STATUS_CANCELLED))
    for a in appts:
        minutes = max(int((a.end_at - a.start_at).total_seconds() // 60), 0)
        booked_minutes[a.doctor_id] = booked_minutes.get(a.doctor_id, 0) + minutes

    by_id = {d.pk: d for d in doctors}
    result = []
    for doctor_id, avail in available_minutes.items():
        doctor = by_id.get(doctor_id)
        if doctor is None or avail <= 0:
            continue
        booked = booked_minutes.get(doctor_id, 0)
        result.append({
            "doctorId": doctor_id,
            "name": doctor.name,
            "occupancyPct": round(booked / avail * 100),
        })
    result.sort(key=lambda r: r["occupancyPct"], reverse=True)
    return result


def _dashboard_funnel_new(clinic, limit=10):
    """Последние необработанные заявки (CRM-воронка, apps.patients.models.Lead,
    stage="new") для карточки на дашборде."""
    from django.utils import timezone
    from apps.patients.models import Lead

    if not clinic:
        return []
    leads = (Lead.objects.filter(clinic=clinic, stage=Lead.STAGE_NEW)
             .order_by("-created_at")[:limit])
    return [{
        "id": lead.pk, "name": lead.name, "phone": lead.phone,
        "createdAt": timezone.localtime(lead.created_at).strftime("%d.%m %H:%M"),
    } for lead in leads]


def _patient_summary_dicts(patients_qs):
    """Общий сериализатор карточки-строки пациента — вынесен из
    _newui_patients_data(), чтобы им же мог пользоваться _newui_patient_by_pk
    (один конкретный пациент по pk, БЕЗ лимита 300 — иначе карточка любого
    пациента "старше" последних 300 созданных не открывалась бы вовсе, см.
    newui_patientcard)."""
    from django.utils import timezone
    from apps.treatments.models import Treatment
    from apps.appointments.models import Appointment

    patients_qs = list(patients_qs)
    ids = [p.pk for p in patients_qs]

    last_visit = {}
    for a in Appointment.objects.filter(patient_id__in=ids, start_at__lte=timezone.now()).order_by("patient_id", "-start_at"):
        last_visit.setdefault(a.patient_id, a.start_at)

    active_treatment_ids = set(
        Treatment.objects.filter(patient_id__in=ids, status__in=[Treatment.STATUS_PLANNED, Treatment.STATUS_IN_PROGRESS])
        .values_list("patient_id", flat=True)
    )

    today = timezone.localdate()
    data = []
    for p in patients_qs:
        age = None
        if p.birth_date:
            age = today.year - p.birth_date.year - ((today.month, today.day) < (p.birth_date.month, p.birth_date.day))
        lv = last_visit.get(p.pk)
        if p.pk in active_treatment_ids:
            status_label, status_color = "В лечении", "amber"
        elif p.balance < 0:
            status_label, status_color = "Должник", "coral"
        else:
            status_label, status_color = ("Активен", "teal") if lv else ("Новый", "cobalt")
        data.append({
            "id": p.pk,
            "fullName": p.full_name,
            "firstName": p.first_name, "lastName": p.last_name, "middleName": p.middle_name,
            "phone": p.phone,
            "birthDate": p.birth_date.strftime("%d.%m.%Y") if p.birth_date else "",
            "birthDateIso": p.birth_date.isoformat() if p.birth_date else "",
            "age": age,
            "gender": p.get_gender_display() if p.gender else "",
            "genderCode": p.gender or "",
            "address": p.address,
            "doctorId": p.primary_doctor_id,
            "doctorName": p.primary_doctor.name if p.primary_doctor else "",
            "sourceId": p.source_id,
            "sourceName": p.source.name if p.source else "",
            "branchId": p.branch_id,
            "allergy": p.allergy or "",
            "balance": float(p.balance),
            "lastVisit": timezone.localtime(lv).strftime("%d.%m.%Y") if lv else "—",
            "sinceLabel": p.created_at.strftime("%m.%Y"),
            "hasActiveTreatment": p.pk in active_treatment_ids,
            "hasDebt": p.balance < 0,
            "statusLabel": status_label,
            "statusColor": status_color,
        })
    return data


def _newui_patients_data():
    """Пациенты клиники для нового интерфейса. Ограничено последними 300 —
    компактный встроенный список для быстрого поиска пациента в модалках
    (запись/касса), НЕ для самого списка (см. _newui_patients_page_data —
    настоящая серверная пагинация на /new/patients/) и НЕ для открытия
    карточки конкретного пациента (см. _newui_patient_by_pk)."""
    from apps.patients.models import Patient

    patients_qs = Patient.objects.select_related("primary_doctor", "source", "branch").order_by("-created_at")[:300]
    return _patient_summary_dicts(patients_qs)


def _newui_patient_by_pk(pk):
    """Один пациент по pk, независимо от лимита 300 в _newui_patients_data —
    используется newui_patientcard, чтобы карточка ЛЮБОГО пациента (не
    только из последних 300 созданных) открывалась корректно."""
    from apps.patients.models import Patient

    p = Patient.objects.select_related("primary_doctor", "source", "branch").filter(pk=pk).first()
    if not p:
        return None
    return _patient_summary_dicts([p])[0]


def _newui_patients_page_data(request):
    """Реальная серверная пагинация/поиск/фильтр для страницы «Пациенты» —
    _newui_patients_data() выше ограничена последними 300 и используется как
    компактный встроенный список для быстрого поиска пациента на ДРУГИХ
    страницах (запись/касса/карточка приёма); в клинике может быть тысячи
    пациентов (напр. 8000+), и рендерить/грузить их всех разом на саму
    страницу списка не годится — здесь настоящий Paginator по queryset."""
    from datetime import timedelta
    from django.core.paginator import Paginator
    from django.db.models import Q, Sum
    from django.utils import timezone
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    from apps.appointments.models import Appointment

    G = request.GET
    q = (G.get("q") or "").strip()
    chip = G.get("filter") or "all"
    try:
        per_page = int(G.get("per_page", 25))
    except (TypeError, ValueError):
        per_page = 25
    per_page = max(10, min(per_page, 200))
    try:
        page_num = int(G.get("page", 1))
    except (TypeError, ValueError):
        page_num = 1

    def _search(qs):
        # Разбиваем на слова, как в старом /patients/ списке — "Иванов Аня"
        # целиком нигде не совпадёт, а по словам находит и ФИО, и телефон.
        for word in q.split():
            qs = qs.filter(
                Q(first_name__icontains=word) | Q(last_name__icontains=word)
                | Q(middle_name__icontains=word) | Q(phone__icontains=word)
            )
        return qs

    active_treatment_qs = Treatment.objects.filter(
        status__in=[Treatment.STATUS_PLANNED, Treatment.STATUS_IN_PROGRESS]
    ).values_list("patient_id", flat=True)

    base_qs = Patient.objects.all()
    if q:
        base_qs = _search(base_qs)
    # Счётчики для чипов «Все/В лечении/Должники» — по queryset с учётом
    # поиска, но БЕЗ учёта самого чипа (иначе счётчик текущего чипа не
    # менялся бы при переключении на другой).
    counts = {
        "all": base_qs.count(),
        "debt": base_qs.filter(balance__lt=0).count(),
        "treatment": base_qs.filter(pk__in=active_treatment_qs).distinct().count(),
    }

    # KPI-блоки сверху страницы (как в старом интерфейсе, templates/patients/list.html)
    # — намеренно от ПОЛНОГО Patient.objects.all() клиники, а не от base_qs
    # (поиск/фильтры их не трогают, как и в старом UI: это общая сводка по
    # клинике, а не по текущей выборке).
    today = timezone.localdate()
    week_ago = today - timedelta(days=7)
    week_ahead = today + timedelta(days=7)
    all_patients_qs = Patient.objects.all()
    new_count = all_patients_qs.filter(created_at__date__gte=week_ago).count()
    birthday_count = 0
    for bd in all_patients_qs.exclude(birth_date=None).values_list("birth_date", flat=True):
        try:
            bd_this_year = bd.replace(year=today.year)
        except ValueError:
            bd_this_year = bd.replace(year=today.year, day=28)  # 29 февраля не в високосный год
        if today <= bd_this_year <= week_ahead:
            birthday_count += 1
    debtors_qs = all_patients_qs.filter(balance__lt=0)
    debtors_total = debtors_qs.aggregate(s=Sum("balance"))["s"] or 0
    stats = {
        "allCount": all_patients_qs.count(),
        "newCount": new_count,
        "birthdayCount": birthday_count,
        "debtorsCount": debtors_qs.count(),
        "debtorsTotal": abs(float(debtors_total)),
    }

    qs = base_qs.select_related("primary_doctor").order_by("-created_at")
    if chip == "debt":
        qs = qs.filter(balance__lt=0)
    elif chip == "treatment":
        qs = qs.filter(pk__in=active_treatment_qs)
    qs = qs.distinct()

    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(page_num)
    ids = [p.pk for p in page_obj.object_list]

    last_visit = {}
    for a in Appointment.objects.filter(patient_id__in=ids, start_at__lte=timezone.now()).order_by("patient_id", "-start_at"):
        last_visit.setdefault(a.patient_id, a.start_at)
    active_treatment_ids = set(
        Treatment.objects.filter(patient_id__in=ids, status__in=[Treatment.STATUS_PLANNED, Treatment.STATUS_IN_PROGRESS])
        .values_list("patient_id", flat=True)
    )

    results = []
    for p in page_obj.object_list:
        lv = last_visit.get(p.pk)
        if p.pk in active_treatment_ids:
            status_label, status_color = "В лечении", "amber"
        elif p.balance < 0:
            status_label, status_color = "Должник", "coral"
        else:
            status_label, status_color = ("Активен", "teal") if lv else ("Новый", "cobalt")
        results.append({
            "id": p.pk,
            "fullName": p.full_name,
            "phone": p.phone,
            "doctorName": p.primary_doctor.name if p.primary_doctor else "",
            "lastVisit": timezone.localtime(lv).strftime("%d.%m.%Y") if lv else "—",
            "balance": float(p.balance),
            "hasDebt": p.balance < 0,
            "hasActiveTreatment": p.pk in active_treatment_ids,
            "statusLabel": status_label,
            "statusColor": status_color,
        })
    return {
        "results": results,
        "page": page_obj.number,
        "perPage": per_page,
        "totalCount": paginator.count,
        "totalPages": paginator.num_pages,
        "counts": counts,
        "stats": stats,
    }


def _newui_services_data():
    """Услуги и категории для нового интерфейса — реальный прайс-лист.
    materialNorms — нормативы расхода материалов на списание (см.
    apps.services.models.ServiceMaterialNorm), та же модель, что уже
    используется автосписанием при завершении приёма (apps.treatments.
    views._auto_writeoff_materials) — здесь просто отдаём их на просмотр/
    редактирование, мутации идут через существующую вьюху старого
    интерфейса apps.services.views.service_edit (action=add_norm/del_norm)."""
    from apps.services.models import Service, ServiceCategory
    categories = list(ServiceCategory.objects.order_by("sort_order", "name"))
    services = [{
        "id": s.pk, "name": s.name, "code": s.code or "",
        "categoryId": s.category_id, "categoryName": s.category.name if s.category else "",
        "price": float(s.price), "isActive": s.is_active, "duration": s.duration,
        "priceSecondary": float(s.price_secondary) if s.price_secondary is not None else None,
        "isLab": s.is_lab,
        "materialNorms": [{"id": n.pk, "productId": n.product_id, "productName": n.product.name,
                            "unit": n.product.unit, "quantity": float(n.quantity)}
                           for n in s.material_norms.select_related("product").all()],
    } for s in Service.objects.select_related("category").prefetch_related("material_norms__product").order_by("category__sort_order", "name")]
    return {
        "services": services,
        "categories": [{"id": c.pk, "name": c.name} for c in categories],
    }


def _newui_finance_data(clinic):
    """Финансы для нового интерфейса — реальные суммы. У макета «Касса» (смены,
    наличные/картой в текущей смене, Z-отчёт) опирается на кассовые смены,
    которых в реальной системе нет как модели — этот раздел размечен как
    неподключённый (см. v-cashdesk), а не подделан."""
    from datetime import timedelta
    from django.db.models import Sum
    from django.utils import timezone
    from apps.finance.models import Payment, Expense, PatientAdvance, ExpenseCategory
    from apps.patients.models import Patient
    from apps.users.models import Branch

    today = timezone.localdate()
    month_start = today.replace(day=1)

    income = Payment.objects.filter(created_at__date__gte=month_start, type=Payment.TYPE_INCOME).aggregate(s=Sum("amount"))["s"] or 0
    refund = Payment.objects.filter(created_at__date__gte=month_start, type=Payment.TYPE_REFUND).aggregate(s=Sum("amount"))["s"] or 0
    revenue_month = float(income - refund)
    expenses_month = float(Expense.objects.filter(created_at__date__gte=month_start).aggregate(s=Sum("amount"))["s"] or 0)
    # PatientAdvance не clinic-scoped моделью (в отличие от Payment/Expense) —
    # фильтруем вручную через пациента, иначе утечка сумм других клиник.
    advances_qs = PatientAdvance.objects.filter(patient__clinic=clinic) if clinic else PatientAdvance.objects.none()
    deposits_total = float(advances_qs.aggregate(s=Sum("amount"))["s"] or 0)
    debtors = Patient.objects.filter(balance__lt=0)
    debt_total = float(-(debtors.aggregate(s=Sum("balance"))["s"] or 0))
    debt_count = debtors.count()

    txns = []
    for p in Payment.objects.select_related("patient", "received_by").order_by("-created_at")[:10]:
        txns.append({
            "who": p.patient.full_name if p.patient else "—",
            "type": "Возврат" if p.type == Payment.TYPE_REFUND else "Оплата",
            "method": p.get_method_display(),
            "amount": float(p.amount) * (-1 if p.type == Payment.TYPE_REFUND else 1),
            "time": timezone.localtime(p.created_at).strftime("%d.%m %H:%M"),
            "paymentId": p.pk,
            "expenseId": None,
        })
    for e in Expense.objects.select_related("category").order_by("-created_at")[:10]:
        txns.append({
            "who": "Клиника", "type": f"Расход · {e.category.name if e.category else '—'}",
            "method": "—", "amount": -float(e.amount),
            "time": timezone.localtime(e.created_at).strftime("%d.%m %H:%M"),
            "paymentId": None,
            "expenseId": e.pk,
        })
    txns.sort(key=lambda t: t["time"], reverse=True)

    branches = [{"id": b.pk, "name": b.name} for b in Branch.objects.filter(is_active=True).order_by("-is_main", "name")]
    expense_categories = [{"id": c.pk, "name": c.name} for c in ExpenseCategory.objects.order_by("name")]

    return {
        "revenueMonth": revenue_month,
        "expensesMonth": expenses_month,
        "depositsTotal": deposits_total,
        "debtTotal": debt_total,
        "debtCount": debt_count,
        "transactions": txns[:12],
        "branches": branches,
        "expenseCategories": expense_categories,
    }


def _newui_lab_data():
    """Заказы лаборатории — реальные данные (apps.technicians), полный набор
    статусов, как в канбане старого интерфейса (apps.technicians.views.
    technician_kanban) — карточки перетаскиваются между колонками, смена
    статуса идёт через ту же вьюху order_status (POST, без AJAX-ветки —
    страница обновляет карточку локально и не перезагружается)."""
    from apps.technicians.models import TechnicianTask
    orders = []
    for t in (TechnicianTask.objects.select_related("patient", "service", "technician")
              .order_by("-created_at")[:200]):
        orders.append({
            "id": t.pk, "code": f"#L-{t.pk:04d}",
            "service": t.service.name if t.service else "",
            "patient": t.patient.full_name if t.patient else "—",
            "patientId": t.patient_id,
            "detail": t.material or (t.tooth_number and f"Зуб {t.tooth_number}") or "",
            "status": t.status,
            "technicianName": t.technician.name if t.technician_id else "—",
            "amount": float(t.amount),
            "expectedReady": t.expected_ready.strftime("%d.%m.%Y") if t.expected_ready else "",
            "isOverdue": t.is_overdue,
        })
    return {
        "orders": orders,
        "statuses": [{"value": v, "label": l} for v, l in TechnicianTask.STATUS_CHOICES],
    }


def _newui_technicians_data():
    """Техники: справочник + расчёты (apps.technicians) — та же видимость,
    что и старый интерфейс (technician_list/technician_payouts). Полное
    редактирование (прайс-лист по услугам, гарантийные случаи, история
    заказов техника) — переход на реальную /technicians/<id>/ (та же
    страница, что и у старого интерфейса, сложную форму с построчными
    расценками и историей не переносим — как и с планами лечения)."""
    from decimal import Decimal
    from django.db.models import Sum
    from apps.technicians.models import Technician, TechnicianTask

    open_counts = {}
    for tid in TechnicianTask.objects.filter(status__in=TechnicianTask.OPEN_STATUSES).values_list("technician_id", flat=True):
        open_counts[tid] = open_counts.get(tid, 0) + 1

    roster, payouts = [], []
    for tech in Technician.objects.filter(is_active=True).order_by("name"):
        roster.append({
            "id": tech.pk,
            "name": tech.name,
            "phone": tech.phone,
            "labName": tech.lab_name,
            "specializationLabel": tech.get_specialization_display() if tech.specialization else "—",
            "openOrders": open_counts.get(tech.pk, 0),
            "balance": float(tech.balance),
        })
        payable = TechnicianTask.objects.filter(technician=tech, status=TechnicianTask.STATUS_INSTALLED, paid=False)
        s = payable.aggregate(x=Sum("amount"))["x"] or Decimal(0)
        cnt = payable.count()
        if cnt:
            payouts.append({"id": tech.pk, "name": tech.name, "sum": float(s), "count": cnt})

    return {
        "roster": roster,
        "payouts": payouts,
        "specializations": [{"value": v, "label": l} for v, l in Technician.SPEC_CHOICES],
    }


def _newui_warehouse_data():
    """Склад материалов — реальные остатки (apps.warehouse). Цена за единицу
    не хранится на Product — берём цену последнего прихода (WarehouseEntry)."""
    from apps.warehouse.models import Product, WarehouseEntry
    products = list(Product.objects.filter(is_active=True).select_related("category").order_by("name"))
    last_price = {}
    for e in WarehouseEntry.objects.filter(product_id__in=[p.pk for p in products]).order_by("product_id", "-date", "-created_at"):
        last_price.setdefault(e.product_id, float(e.price))

    low_stock = [p for p in products if p.quantity <= p.min_qty]
    total_value = sum(float(p.quantity) * last_price.get(p.pk, 0) for p in products)
    items = []
    for p in products:
        qty, min_qty = float(p.quantity), float(p.min_qty)
        status = "order" if qty <= min_qty else ("low" if qty <= min_qty * 1.5 else "ok")
        items.append({
            "id": p.pk, "name": p.name, "quantity": qty, "unit": p.unit,
            "minQty": min_qty, "status": status,
        })
    return {
        "items": items,
        "lowStockCount": len(low_stock),
        "totalValue": total_value,
        "activeCount": len(products),
    }


def _newui_warehouse_ops_data():
    """Операции склада — поступления/списания/перемещения/инвентаризации
    (apps.warehouse), для отдельных вкладок страницы «Склад» в новом
    интерфейсе. Создание идёт через ТЕ ЖЕ вьюхи-формы старого интерфейса
    (apps.warehouse.views: entry_create/distribution_create/transfer_create/
    inventory_create — POST + res.redirected → flashAndReload), включая
    множественные позиции одним запросом (getlist по product/quantity/...),
    как и в старом интерфейсе — бизнес-логика не дублируется."""
    from apps.warehouse.models import (
        Product, ProductCategory, Supplier, WarehouseEntry, WarehouseDistribution,
        WarehouseTransfer, InventoryDocument,
    )
    from apps.users.models import Branch, User

    entries = [{
        "id": e.pk, "product": e.product.name if e.product_id else "—",
        "quantity": float(e.quantity), "unit": e.product.unit if e.product_id else "",
        "price": float(e.price), "supplier": e.supplier.name if e.supplier_id else "—",
        "date": e.date.strftime("%d.%m.%Y"),
    } for e in WarehouseEntry.objects.select_related("product", "supplier").order_by("-date", "-id")[:100]]

    distributions = [{
        "id": d.pk, "product": d.product.name if d.product_id else "—",
        "quantity": float(d.quantity), "unit": d.product.unit if d.product_id else "",
        "branch": d.branch.name if d.branch_id else "—",
        "issuedTo": d.issued_to.name if d.issued_to_id else "—",
        "date": d.date.strftime("%d.%m.%Y"),
    } for d in WarehouseDistribution.objects.select_related("product", "branch", "issued_to").order_by("-date", "-id")[:100]]

    transfers = [{
        "id": tr.pk, "fromBranch": tr.from_branch.name if tr.from_branch_id else "—",
        "toBranch": tr.to_branch.name if tr.to_branch_id else "—",
        "date": tr.date.strftime("%d.%m.%Y"),
        "items": [{"product": it.product.name if it.product_id else "—", "quantity": float(it.quantity)} for it in tr.items.select_related("product").all()],
    } for tr in WarehouseTransfer.objects.select_related("from_branch", "to_branch").prefetch_related("items__product").order_by("-date", "-id")[:100]]

    inventories = [{
        "id": inv.pk, "branch": inv.branch.name if inv.branch_id else "—",
        "date": inv.date.strftime("%d.%m.%Y"), "status": inv.status,
        "statusLabel": inv.get_status_display(),
    } for inv in InventoryDocument.objects.select_related("branch").order_by("-date", "-id")[:100]]

    return {
        "entries": entries,
        "distributions": distributions,
        "transfers": transfers,
        "inventories": inventories,
        "products": [{"id": p.pk, "name": p.name, "unit": p.unit, "quantity": float(p.quantity)}
                     for p in Product.objects.filter(is_active=True).order_by("name")],
        "categories": [{"id": c.pk, "name": c.name} for c in ProductCategory.objects.order_by("name")],
        "suppliers": [{"id": s.pk, "name": s.name} for s in Supplier.objects.filter(is_active=True).order_by("name")],
        "branches": [{"id": b.pk, "name": b.name} for b in Branch.objects.filter(is_active=True).order_by("name")],
        # Лёгкий список сотрудников для «Кому выдано» (WarehouseDistribution.
        # issued_to) — полный _newui_staff_data() тяжелее и нужен только
        # странице «Персонал».
        "staff": [{"id": u.pk, "name": u.name} for u in User.objects.filter(is_active=True).order_by("name")],
    }


def _newui_reports_data():
    """Отчёты для нового интерфейса — верхние real-KPI «Общего отчёта», графики
    на нём же (выручка по неделям, загрузка врачей, источники заявок, причины
    отмены) и реальные вкладки Расходы/Должники/Отменённые визиты/Статистика по
    врачам/Источники заявок/Повторные визиты/Загрузка кабинетов (период — текущий
    месяц, кроме «Повторных визитов» — там вся история, иначе повторность не
    увидеть, и «Загрузки кабинетов» — там текущая неделя, см. ниже).
    «Загрузка кабинетов» — часы заняты реальными (сумма длительности приёмов
    по Appointment.cabinet за текущую неделю), а «загрузка» — честная доля
    кабинета от суммарных часов по всем кабинетам (не % от «рабочих часов» —
    такой модели в системе нет, у кабинета нет своего графика работы в
    отличие от врача). Конструктор сравнения — реальные датасеты по 4
    измерениям (doctors/rooms/services/sources), см. comparison ниже; кроме
    «Материалы» — списания склада не привязаны ни к пациенту, ни к приёму,
    выручку/количество по материалам посчитать нечем без новых полей в
    модели, поэтому этого измерения в выборе больше нет вообще (не показываем
    вкладку с обещанием, которое нечем выполнить). ИИ-помощник НЕ подключен —
    см. баннер на странице; ИИ-рекомендаций как функции в системе не
    существует."""
    from datetime import timedelta
    from collections import defaultdict
    from django.db.models import Sum, Count, Max
    from django.utils import timezone
    from apps.finance.models import Payment, Expense
    from apps.appointments.models import Appointment
    from apps.patients.models import Patient, Lead
    from apps.treatments.models import Treatment

    today = timezone.localdate()
    month_start = today.replace(day=1)
    income = Payment.objects.filter(created_at__date__gte=month_start, type=Payment.TYPE_INCOME).aggregate(s=Sum("amount"))["s"] or 0
    refund = Payment.objects.filter(created_at__date__gte=month_start, type=Payment.TYPE_REFUND).aggregate(s=Sum("amount"))["s"] or 0
    month_appts = Appointment.objects.filter(start_at__date__gte=month_start)
    completed = month_appts.filter(status=Appointment.STATUS_COMPLETED).count()
    cancelled = month_appts.filter(status=Appointment.STATUS_CANCELLED).count()
    noshow = month_appts.filter(status=Appointment.STATUS_NO_SHOW).count()
    total = month_appts.count()

    # ── Расходы (Expense/ExpenseCategory) — за месяц ──
    expenses_qs = Expense.objects.filter(date__gte=month_start).select_related("category")
    expenses_total = float(expenses_qs.aggregate(s=Sum("amount"))["s"] or 0)
    expenses_by_cat = list(
        expenses_qs.values("category__name").annotate(total=Sum("amount")).order_by("-total")
    )
    expenses_list = [{
        "date": e.date.strftime("%d.%m.%Y"), "category": e.category.name if e.category else "—",
        "amount": float(e.amount), "description": e.description,
    } for e in expenses_qs.order_by("-date")[:100]]

    # ── Должники — тот же запрос, что и старый /finance/payments/debtors/ ──
    debtors_qs = Patient.objects.filter(balance__lt=0).order_by("balance")
    debtors_list = [{"id": p.pk, "name": p.full_name, "phone": p.phone, "balance": float(p.balance)} for p in debtors_qs[:200]]
    debtors_total = float(sum(p["balance"] for p in debtors_list))

    # ── Отменённые визиты (cancelled + no-show) — за месяц. Причина — только у
    # статуса «Отменён» (cancellation_reason на Appointment реально есть — см.
    # cancel_reasons_chart ниже); у «Не пришёл» её не выбирают, там просто «—». ──
    cancelled_qs = (month_appts.filter(status__in=[Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW])
                     .select_related("patient", "doctor", "cancellation_reason").order_by("-start_at"))
    cancelled_list = [{
        "date": timezone.localtime(a.start_at).strftime("%d.%m.%Y"),
        "patient": a.patient.full_name if a.patient else "—",
        "doctor": a.doctor.name if a.doctor else "—",
        "status": a.get_status_display(),
        "statusColor": "coral" if a.status == Appointment.STATUS_CANCELLED else "amber",
        "reason": a.cancellation_reason.name if a.cancellation_reason_id else "—",
    } for a in cancelled_qs[:200]]

    # ── Статистика по врачам — завершённые/оплаченные приёмы за месяц ──
    doctor_treatments = (Treatment.objects.filter(
        created_at__date__gte=month_start, status__in=[Treatment.STATUS_COMPLETED, Treatment.STATUS_PAID],
    ).values("doctor__name").annotate(cnt=Count("id"), revenue=Sum("total_amount")).order_by("-revenue"))
    doctor_appt_totals = dict(month_appts.values_list("doctor__name").annotate(cnt=Count("id")))
    doctor_appt_completed = dict(month_appts.filter(status=Appointment.STATUS_COMPLETED).values_list("doctor__name").annotate(cnt=Count("id")))
    doctor_stats = []
    for row in doctor_treatments:
        name = row["doctor__name"] or "—"
        cnt = row["cnt"]
        revenue = float(row["revenue"] or 0)
        appt_total = doctor_appt_totals.get(name, 0)
        appt_done = doctor_appt_completed.get(name, 0)
        doctor_stats.append({
            "doctor": name, "count": cnt, "revenue": revenue,
            "avgCheck": round(revenue / cnt, 2) if cnt else 0,
            "fillRatePct": round(appt_done / appt_total * 100, 1) if appt_total else 0,
        })

    # ── Источники заявок (Lead/LeadSource) — за месяц, конверсия = дошли/завершено
    # из всех заявок этого источника (грубая, но реальная метрика; стоимость
    # привлечения не считаем — в LeadSource такого поля нет). Заодно копим
    # id связанных пациентов по источнику — для «Конструктора сравнения»
    # (реальная выручка по источнику, см. comparison ниже). ──
    month_leads = Lead.objects.filter(created_at__date__gte=month_start).select_related("source")
    sources = {}
    source_patient_ids = {}
    for lead in month_leads:
        key = lead.source.name if lead.source else "Без источника"
        s = sources.setdefault(key, {"source": key, "count": 0, "converted": 0})
        s["count"] += 1
        if lead.stage in (Lead.STAGE_CAME, Lead.STAGE_COMPLETED):
            s["converted"] += 1
        if lead.patient_id:
            source_patient_ids.setdefault(key, set()).add(lead.patient_id)
    lead_sources = sorted(
        [{"source": s["source"], "count": s["count"],
          "conversionPct": round(s["converted"] / s["count"] * 100, 1) if s["count"] else 0}
         for s in sources.values()],
        key=lambda x: -x["count"],
    )
    source_revenue = {}
    for key, pids in source_patient_ids.items():
        rev = (Treatment.objects.filter(patient_id__in=pids, created_at__date__gte=month_start)
               .exclude(status="cancelled").aggregate(s=Sum("total_amount"))["s"] or 0)
        source_revenue[key] = float(rev)

    # ── Услуги — выручка/количество за месяц (TreatmentCure.subtotal — цена со
    # скидкой, тот же расчёт, что и в самой карточке приёма). Для «Конструктора
    # сравнения» — своей отдельной вкладки в отчётах у услуг нет. ──
    from apps.treatments.models import TreatmentCure
    service_agg = {}
    cures_qs = (TreatmentCure.objects.filter(treatment__created_at__date__gte=month_start)
                .exclude(treatment__status="cancelled").select_related("service"))
    for cure in cures_qs:
        key = cure.service.name if cure.service_id else "Без услуги"
        row = service_agg.setdefault(key, {"count": 0, "revenue": 0.0})
        row["count"] += cure.quantity
        row["revenue"] += float(cure.subtotal)
    top_services = sorted(service_agg.items(), key=lambda kv: -kv[1]["revenue"])[:10]

    # ── Выручка по неделям месяца (для «Общего отчёта» — раньше был статичный
    # захардкоженный график). Недели считаем простыми блоками по 7 дней от
    # начала месяца (1-7, 8-14, ...), а не календарными — проще и достаточно
    # для тренда внутри месяца. ──
    import calendar
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    week_count = (days_in_month - 1) // 7 + 1
    weekly_net = [0.0] * week_count
    month_income_refund = Payment.objects.filter(
        created_at__date__gte=month_start, created_at__date__lte=today,
        type__in=[Payment.TYPE_INCOME, Payment.TYPE_REFUND],
    ).only("amount", "type", "created_at")
    for p in month_income_refund:
        week_idx = (timezone.localtime(p.created_at).date().day - 1) // 7
        weekly_net[week_idx] += float(p.amount) if p.type == Payment.TYPE_INCOME else -float(p.amount)
    weekly_revenue = [{"label": "Нед. %d" % (i + 1), "value": round(v, 2)} for i, v in enumerate(weekly_net)]

    # ── Причины отмены визитов — Appointment.cancellation_reason реально есть
    # в модели (несмотря на старый комментарий выше — он был неверным), просто
    # заполняется только когда причину явно выбрали при отмене. ──
    cancel_reasons_qs = (
        month_appts.filter(status=Appointment.STATUS_CANCELLED, cancellation_reason__isnull=False)
        .values("cancellation_reason__name").annotate(cnt=Count("id")).order_by("-cnt")
    )
    cancel_reasons_chart = [{"reason": c["cancellation_reason__name"], "count": c["cnt"]} for c in cancel_reasons_qs]

    # ── Повторные визиты — визитов на пациента (все завершённые приёмы, не
    # только этот месяц — иначе «повторность» не увидеть) + дата последнего. ──
    patient_visits = (
        Appointment.objects.filter(status=Appointment.STATUS_COMPLETED, patient__isnull=False)
        .values("patient_id", "patient__last_name", "patient__first_name", "patient__middle_name")
        .annotate(cnt=Count("id"), last_at=Max("start_at"))
        .order_by("-cnt")
    )
    repeat_visits = [{
        "patientId": row["patient_id"],
        "patient": " ".join(p for p in (row["patient__last_name"], row["patient__first_name"], row["patient__middle_name"]) if p) or "—",
        "count": row["cnt"],
        "lastVisit": timezone.localtime(row["last_at"]).strftime("%d.%m.%Y") if row["last_at"] else "—",
        "daysSince": (today - timezone.localtime(row["last_at"]).date()).days if row["last_at"] else None,
    } for row in patient_visits[:200]]

    # ── Загрузка кабинетов — часы заняты за ТЕКУЩУЮ неделю (пн-вс), реальная
    # сумма длительности приёмов по Appointment.cabinet (не только этот месяц,
    # т.к. таблица так и называется «...· неделя» — короткое окно нагляднее).
    # Отменённые/неявки в занятость кабинета не считаем — кабинет ими не занят. ──
    week_start = today - timedelta(days=today.weekday())
    week_appts = (Appointment.objects.filter(
        start_at__date__gte=week_start, start_at__date__lt=week_start + timedelta(days=7),
        cabinet__isnull=False,
    ).exclude(status__in=[Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW]).select_related("cabinet"))
    cabinet_hours = defaultdict(float)
    for a in week_appts:
        cabinet_hours[a.cabinet.name] += (a.end_at - a.start_at).total_seconds() / 3600.0
    total_cabinet_hours = sum(cabinet_hours.values())
    room_load = sorted([
        {"room": name, "hours": round(hrs, 1),
         "sharePct": round(hrs / total_cabinet_hours * 100, 1) if total_cabinet_hours else 0}
        for name, hrs in cabinet_hours.items()
    ], key=lambda x: -x["hours"])

    # ── Конструктор сравнения — реальные датасеты по 4 измерениям (не 5:
    # «Материалы» убраны из выбора — списания склада не привязаны ни к
    # пациенту, ни к приёму (WarehouseDistribution.issued_to — это сотрудник,
    # получивший материал, а не потраченный на кого-то), выручку/количество
    # по материалам посчитать нечем без нового поля в модели). Показатель,
    # для которого у измерения нет данных (напр. avgcheck у кабинетов),
    # просто не заполняем — buildBarChart/buildDonutChart сами покажут
    # «Нет данных» вместо выдумки. ──
    comparison = {
        "doctors": {
            "revenue": [{"label": d["doctor"], "value": d["revenue"]} for d in doctor_stats],
            "count": [{"label": d["doctor"], "value": d["count"]} for d in doctor_stats],
            "avgcheck": [{"label": d["doctor"], "value": d["avgCheck"]} for d in doctor_stats],
            "utilization": [{"label": d["doctor"], "value": d["fillRatePct"]} for d in doctor_stats],
        },
        "rooms": {
            "count": [{"label": r["room"], "value": r["hours"]} for r in room_load],
            "utilization": [{"label": r["room"], "value": r["sharePct"]} for r in room_load],
        },
        "services": {
            "revenue": [{"label": name, "value": round(v["revenue"], 2)} for name, v in top_services],
            "count": [{"label": name, "value": v["count"]} for name, v in top_services],
            "avgcheck": [{"label": name, "value": round(v["revenue"] / v["count"], 2) if v["count"] else 0} for name, v in top_services],
        },
        "sources": {
            "count": [{"label": s["source"], "value": s["count"]} for s in lead_sources],
            "revenue": [{"label": s["source"], "value": source_revenue.get(s["source"], 0)} for s in lead_sources],
        },
    }

    return {
        "revenueMonth": float(income - refund),
        "completed": completed,
        "cancelled": cancelled,
        "cancelledPct": round(cancelled / total * 100, 1) if total else 0,
        "noshow": noshow,
        "expensesTotal": expenses_total,
        "expensesByCategory": [{"category": c["category__name"] or "Без категории", "total": float(c["total"])} for c in expenses_by_cat],
        "expensesList": expenses_list,
        "debtorsTotal": debtors_total,
        "debtorsList": debtors_list,
        "cancelledVisits": cancelled_list,
        "doctorStats": doctor_stats,
        "leadSources": lead_sources,
        "weeklyRevenue": weekly_revenue,
        "cancelReasons": cancel_reasons_chart,
        "repeatVisits": repeat_visits,
        "roomLoad": room_load,
        "comparison": comparison,
    }


def _newui_schedule_data(clinic):
    """Расписание врачей для нового интерфейса — реальные врачи и реальные
    приёмы в окне ±30 дней от сегодня (день/неделя/месяц листаются внутри
    этого окна). Создание записи кликом по пустой ячейке и перетаскивание
    записи между ячейками/врачами подключены к тем же view, что и старый
    интерфейс — appointment_create_quick / appointment_move (см. схему
    day_grid.html), логика конфликтов/расписания не дублируется."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.users.models import clinic_doctors
    from apps.appointments.models import Appointment

    doctors = list(clinic_doctors(clinic).order_by("name")) if clinic else []
    doctor_ids = [d.pk for d in doctors]
    doctors_data = [{
        "id": d.pk, "init": initials_of(d.name), "name": d.name,
        "role": d.role.display_name if d.role else "",
        "color": d.color or "",
    } for d in doctors]

    today = timezone.localdate()
    window_start = today - timedelta(days=30)
    window_end = today + timedelta(days=30)
    appts_qs = (Appointment.objects
                .filter(doctor_id__in=doctor_ids, start_at__date__gte=window_start, start_at__date__lte=window_end)
                .exclude(status=Appointment.STATUS_CANCELLED)
                .select_related("patient", "service", "created_by").order_by("start_at"))

    status_color = {
        Appointment.STATUS_SCHEDULED: "cobalt", Appointment.STATUS_CONFIRMED: "cobalt",
        Appointment.STATUS_ARRIVED: "amber", Appointment.STATUS_IN_PROGRESS: "amber",
        Appointment.STATUS_COMPLETED: "teal", Appointment.STATUS_NO_SHOW: "coral",
    }
    # Завершённые приёмы — красим по факту оплаты (Treatment.debt), а не
    # одним цветом «завершён»: не оплачен (есть долг) — красный, оплачен
    # полностью — зелёный. Одним запросом по всем id окна, чтобы не плодить
    # N+1 на списке из ±30-дневного окна расписания.
    from apps.treatments.models import Treatment
    completed_ids = [a.pk for a in appts_qs if a.status == Appointment.STATUS_COMPLETED]
    debt_by_appt = {
        t.appointment_id: t.debt
        for t in Treatment.objects.filter(appointment_id__in=completed_ids).only(
            "appointment_id", "total_amount", "discount", "paid_amount", "status"
        )
    }
    appts_data = [{
        "id": a.pk,
        "date": timezone.localtime(a.start_at).date().isoformat(),
        "time": timezone.localtime(a.start_at).strftime("%H:%M"),
        "docId": a.doctor_id,
        "patientId": a.patient_id,
        "patient": a.patient.full_name if a.patient else "Без пациента",
        "service": a.service.name if a.service else "",
        "status": (
            ("coral" if debt_by_appt[a.pk] > 0 else "teal")
            if a.status == Appointment.STATUS_COMPLETED and a.pk in debt_by_appt
            else status_color.get(a.status, "cobalt")
        ),
        # Сырой статус (scheduled/confirmed/arrived/...), в отличие от
        # "status" выше, который на самом деле цвет пилюли — нужен голосовым
        # командам расписания, чтобы отличать завершённые/отменённые записи
        # от активных без парсинга цвета.
        "statusRaw": a.status,
        # Человекочитаемый статус (Appointment.STATUS_CHOICES) — для подсказки
        # при наведении на карточку (statusRaw там же используется для иконки).
        "statusDisplay": a.get_status_display(),
        "durationMin": max(int((a.end_at - a.start_at).total_seconds() // 60), 1),
        "movable": a.status not in (Appointment.STATUS_COMPLETED, Appointment.STATUS_NO_SHOW),
        # Общий долг пациента (Patient.debt, а не долг конкретно ЭТОГО приёма) —
        # для подсветки на сетке расписания, независимо от статуса приёма.
        "debt": float(a.patient.debt) if a.patient_id else 0,
        # Всё ниже — только для подсказки при наведении на карточку записи
        # (schedApptHoverShow), сама сетка это не использует.
        "patientPhone": a.patient.phone if a.patient_id else "",
        "patientAge": a.patient.age if a.patient_id else None,
        "patientBirthDate": a.patient.birth_date.strftime("%d.%m.%Y") if (a.patient_id and a.patient.birth_date) else "",
        "cardNumber": a.patient.display_number if a.patient_id else None,
        "createdBy": a.created_by.name if a.created_by_id else "",
        "notes": a.notes or "",
    } for a in appts_qs]

    return {
        "doctors": doctors_data,
        "appointments": appts_data,
        "windowStart": window_start.isoformat(),
        "windowEnd": window_end.isoformat(),
    }


def _newui_blacklist_data():
    """Общий чёрный список — та же модель и те же данные, что и в старом
    интерфейсе (apps.patients.views.blacklist_view), просто отрисованы в
    новом дизайне. Добавление/удаление идут через тот же view (/patients/blacklist/)."""
    from apps.patients.models import BlacklistEntry
    entries = BlacklistEntry.objects.select_related("clinic", "added_by").order_by("-created_at")[:300]
    return [{
        "id": e.pk,
        "name": e.name or "—",
        "phone": e.phone,
        "reason": e.reason,
        "addedBy": e.added_by.name if e.added_by else "—",
        "date": e.created_at.strftime("%d.%m.%Y"),
    } for e in entries]


def _newui_visits_journal_data(request, clinic):
    """Журнал посещений — та же модель и та же агрегация, что и в старом
    интерфейсе (apps.patients.views.visits_journal): по каждому пациенту —
    сколько раз был и когда последний, первичные (1 раз)/вторичные (2+).
    Мутации (добавить/удалить посещение, переключить видимость персоналу)
    идут через тот же view (/patients/journal/, POST + res.redirected), эта
    функция — только чтение, дублирования бизнес-логики нет. Видимость самой
    страницы персоналу — apps.patients.views._visits_journal_allowed."""
    from django.db.models import Count, Max
    from django.utils import timezone
    from apps.patients.models import Patient, PatientVisit
    from apps.settings_clinic.models import ClinicSettings

    agg = list(PatientVisit.objects.values("patient")
               .annotate(cnt=Count("id"), last=Max("visited_at")).order_by("-last"))
    pat_ids = [a["patient"] for a in agg]
    pmap = {p.pk: p for p in Patient.objects.filter(pk__in=pat_ids)}
    rows = []
    for a in agg:
        p = pmap.get(a["patient"])
        if not p:
            continue
        rows.append({
            "patientId": p.pk, "patientName": p.full_name, "patientPhone": p.phone or "",
            "count": a["cnt"], "primary": a["cnt"] == 1,
            "last": timezone.localtime(a["last"]).strftime("%d.%m.%Y %H:%M"),
        })
    today = timezone.localdate()
    cs = ClinicSettings.get()
    return {
        "rows": rows,
        "totalVisits": PatientVisit.objects.count(),
        "visitsToday": PatientVisit.objects.filter(visited_at__date=today).count(),
        "uniqPatients": len(pat_ids),
        "primaryCount": sum(1 for a in agg if a["cnt"] == 1),
        "secondaryCount": sum(1 for a in agg if a["cnt"] > 1),
        "canToggle": bool(request.user.is_superadmin or request.user.is_admin_main),
        "visitsJournalStaff": bool(cs.visits_journal_staff),
    }


def _newui_tasks_data(request, clinic):
    """Задачи — та же модель и те же права видимости, что и в старом
    интерфейсе (apps.tasks.views.task_list): админ/суперадмин видят все
    задачи клиники, остальные — только свои (назначенные им или созданные
    ими). Создание/редактирование/готово/удаление идут через те же вьюхи
    apps.tasks.views (POST + res.redirected на клиенте, как «Чёрный список»
    и «Персонал» — без дублирования бизнес-логики форм в новом интерфейсе)."""
    from django.db.models import Q, F
    from django.utils import timezone
    from django.utils.timezone import localtime
    from apps.tasks.models import Task
    from apps.users.models import User

    qs = Task.objects.prefetch_related("assigned_to").select_related("created_by")
    if not request.user.is_superadmin and not request.user.is_admin:
        qs = qs.filter(Q(assigned_to=request.user) | Q(created_by=request.user)).distinct()
    qs = qs.order_by(F("due_date").asc(nulls_last=True), "-created_at")

    tasks = [{
        "id": tsk.pk,
        "title": tsk.title,
        "description": tsk.description,
        "status": tsk.status,
        "priority": tsk.priority,
        "dueDate": tsk.due_date.strftime("%Y-%m-%dT%H:%M") if tsk.due_date else "",
        "dueDateDisplay": localtime(tsk.due_date).strftime("%d.%m.%Y %H:%M") if tsk.due_date else "",
        "overdue": bool(tsk.due_date and tsk.status != Task.STATUS_DONE and tsk.due_date < timezone.now()),
        "assignedTo": [{"id": u.pk, "name": u.name} for u in tsk.assigned_to.all()],
        "createdById": tsk.created_by_id,
        "createdBy": tsk.created_by.name if tsk.created_by_id else "—",
    } for tsk in qs]

    # Себя не предлагаем в исполнители — так же, как старый интерфейс
    # (apps.tasks.forms.TaskForm.__init__ строит queryset "assigned_to" без
    # текущего пользователя): иначе выбор себя же на клиенте прошёл бы, а
    # сервер бы его отклонил как невалидный выбор при сохранении формы.
    staff_qs = User.objects.filter(is_active=True).exclude(pk=request.user.pk)
    if clinic is not None:
        staff_qs = staff_qs.filter(clinic=clinic)
    staff = [{"id": u.pk, "name": u.name} for u in staff_qs.order_by("name")]
    return {"tasks": tasks, "staff": staff}


def _newui_medicines_data(request):
    """Лекарства — та же модель и те же права видимости, что и в старом
    интерфейсе (apps.medicines.views.medicine_list): врач видит только свои
    назначения, остальные — все. Добавление лекарства на склад/назначение
    пациенту идут через те же вьюхи apps.medicines.views (POST +
    res.redirected на клиенте — как «Задачи»/«Чёрный список»). Редактирования
    и удаления нет и у старого интерфейса — не добавляем их и здесь."""
    from apps.medicines.models import Medicine, PatientMedicine

    medicines = [{
        "id": m.pk,
        "name": m.name,
        "form": m.form,
        "formLabel": m.get_form_display(),
        "quantity": float(m.quantity),
        "unit": m.unit,
        "minQty": float(m.min_qty),
        "low": m.quantity <= m.min_qty,
    } for m in Medicine.objects.filter(is_active=True).order_by("name")]

    presc_qs = PatientMedicine.objects.select_related("patient", "medicine", "doctor").order_by("-date")
    if request.user.is_doctor:
        presc_qs = presc_qs.filter(doctor=request.user)
    prescriptions = [{
        "id": p.pk,
        "patientId": p.patient_id,
        "patientName": p.patient.full_name,
        "medicineName": p.medicine.name,
        "dosage": p.dosage,
        "duration": p.duration,
        "doctorName": p.doctor.name if p.doctor_id else "—",
        "date": p.date.strftime("%d.%m.%Y"),
    } for p in presc_qs[:50]]

    return {"medicines": medicines, "prescriptions": prescriptions}


def _newui_recycle_data(request):
    """Корзина — те же модели/данные, что и старый интерфейс
    (apps.users.views.recycle_bin: _recycle_models()/_recycle_qs()).
    Восстановление идёт через ту же вьюху POST-формы старого интерфейса
    (res.redirected → flashAndReload). Безвозвратное удаление — ссылка на
    существующую страницу-предупреждение старого интерфейса
    (recycle_purge_confirm, показывает связанные записи/долг перед покупкой
    необратимого действия) — не дублируем эту безопасность здесь заново."""
    models = _recycle_models()
    items = []
    counts = {}
    for kind, (Model, label) in models.items():
        qs = _recycle_qs(Model)
        counts[kind] = qs.count()
        for obj in qs.order_by("-deleted_at")[:300]:
            items.append({
                "kind": kind,
                "label": label,
                "pk": obj.pk,
                "title": str(obj),
                "deletedAt": obj.deleted_at.strftime("%d.%m.%Y %H:%M") if obj.deleted_at else "",
                "deletedAtRaw": obj.deleted_at.isoformat() if obj.deleted_at else "",
                "deletedBy": obj.deleted_by.name if obj.deleted_by_id else "—",
            })
    items.sort(key=lambda x: x["deletedAtRaw"], reverse=True)
    cats = [{"kind": k, "label": models[k][1], "count": counts.get(k, 0)} for k in models]
    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()
    return {
        "items": items, "cats": cats, "total": sum(counts.values()),
        "canToggle": bool(request.user.is_superadmin or request.user.is_admin_main),
        "recycleBinStaff": bool(cs.recycle_bin_staff),
    }


def _newui_treatplans_data(clinic):
    """Планы лечения — реальная модель TreatmentPlan (apps.treatments.models_plan),
    та же, что используется в редакторе плана старого интерфейса (plan_detail).
    Полноценный редактор этапов/услуг в новом интерфейсе не переносим (сложная
    форма с построчным добавлением услуг) — переход на реальный /treatments/plans/<id>/."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.treatments.models_plan import TreatmentPlan

    qs = TreatmentPlan.objects.filter(patient__clinic=clinic) if clinic else TreatmentPlan.objects.none()
    qs = qs.select_related("patient", "doctor").prefetch_related("stages", "items")

    today = timezone.localdate()
    month_start = today.replace(day=1)

    plans = []
    active_count = 0
    completed_month = 0
    awaiting_payment = 0
    for p in qs.order_by("-created_at")[:300]:
        stage_titles = [s.title for s in p.stages.all() if s.title]
        total = p.total_price
        done = p.done_price
        if p.status in (TreatmentPlan.STATUS_APPROVED, TreatmentPlan.STATUS_IN_PROGRESS):
            active_count += 1
        if p.status == TreatmentPlan.STATUS_COMPLETED and timezone.localtime(p.updated_at).date() >= month_start:
            completed_month += 1
        if p.status == TreatmentPlan.STATUS_COMPLETED and done < total:
            awaiting_payment += 1
        plans.append({
            "id": p.pk,
            "patientId": p.patient_id,
            "patient": p.patient.full_name,
            "stage": stage_titles[0] if stage_titles else p.title,
            "doctor": p.doctor.name if p.doctor else "—",
            "completionPct": p.completion_pct,
            "totalPrice": float(total),
            "status": p.get_status_display(),
            "statusCode": p.status,
        })

    return {
        "plans": plans,
        "activeCount": active_count,
        "completedMonthCount": completed_month,
        "awaitingPaymentCount": awaiting_payment,
    }


def _newui_visits_data(clinic):
    """«Визиты» — реальные записи (Appointment), та же модель, что и
    /new/schedule/ и старый интерфейс. Смена статуса идёт через тот же
    appointment_status, что и старый интерфейс (без дублирования логики).
    Окно ±30 дней от сегодня (не вся история — на живой клинике это могут
    быть тысячи записей), вкладка «Все» на фронте снимает фильтр по дню,
    но не по этому окну."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.appointments.models import Appointment
    from apps.users.models import clinic_doctors

    doctor_ids = list(clinic_doctors(clinic).values_list("pk", flat=True)) if clinic else []
    today = timezone.localdate()
    appts = list(Appointment.objects.filter(
              doctor_id__in=doctor_ids,
              start_at__date__gte=today - timedelta(days=30),
              start_at__date__lte=today + timedelta(days=30),
          )
          .select_related("patient", "doctor", "service").order_by("-start_at")[:500])

    # Чек приёма (apps.treatments.views.treatment_print) печатается по
    # Treatment.pk и работает БЕЗ оплаты (QR ведёт на публичную страницу
    # приёма) — находим приём, привязанный к визиту, чтобы дать кнопку
    # «Печать чека» в списке визитов не дожидаясь платежа.
    from apps.treatments.models import Treatment
    appt_ids = [a.pk for a in appts]
    latest_treatment_by_appt = {}
    for tr_id, appt_id in (Treatment.objects.filter(appointment_id__in=appt_ids)
                            .order_by("appointment_id", "-created_at").values_list("id", "appointment_id")):
        latest_treatment_by_appt.setdefault(appt_id, tr_id)

    status_label = dict(Appointment.STATUS_CHOICES)
    status_pill = {
        Appointment.STATUS_SCHEDULED: "cobalt", Appointment.STATUS_CONFIRMED: "cobalt",
        Appointment.STATUS_ARRIVED: "amber", Appointment.STATUS_IN_PROGRESS: "amber",
        Appointment.STATUS_COMPLETED: "teal", Appointment.STATUS_NO_SHOW: "coral",
        Appointment.STATUS_CANCELLED: "coral",
    }
    visits = [{
        "id": a.pk,
        "date": timezone.localtime(a.start_at).strftime("%Y-%m-%d"),
        "dateLabel": timezone.localtime(a.start_at).strftime("%d.%m.%Y"),
        "time": timezone.localtime(a.start_at).strftime("%H:%M"),
        "patient": a.patient.full_name if a.patient else "Без пациента",
        "patientId": a.patient_id,
        "doctor": a.doctor.name if a.doctor else "—",
        "service": a.service.name if a.service else "—",
        "status": a.status,
        "statusLabel": status_label.get(a.status, a.status),
        "statusColor": status_pill.get(a.status, "cobalt"),
        "treatmentId": latest_treatment_by_appt.get(a.pk),
    } for a in appts]
    today_iso = today.strftime("%Y-%m-%d")
    today_visits = [v for v in visits if v["date"] == today_iso]

    return {
        "visits": visits,
        "todayIso": today_iso,
        "totalToday": len(today_visits),
        "plannedCount": sum(1 for v in today_visits if v["status"] in (Appointment.STATUS_SCHEDULED, Appointment.STATUS_CONFIRMED)),
        "openCount": sum(1 for v in today_visits if v["status"] in (Appointment.STATUS_ARRIVED, Appointment.STATUS_IN_PROGRESS)),
    }


def _newui_accounting_data(clinic):
    """Бухгалтерия — реальная выручка (Payment) и расходы по реальным
    категориям клиники (ExpenseCategory/Expense) за месяц. В системе нет
    модели зарплат/аренды как отдельной проводки — показываем только то, что
    реально заведено клиникой как категория расхода.

    Дополнительно (по запросу «сделай более богатой страницей»):
    - dailySeries — выручка/расходы по дням месяца, для графика тренда, а не
      только итогового числа.
    - revenueByService/revenueByDoctor — разбивка выручки. В системе нет
      оплаты по отдельной позиции приёма (Payment↔Treatment — приём целиком,
      см. PaymentAllocation), поэтому сумма оплаты распределяется по
      позициям приёма (TreatmentCure) ПРОПОРЦИОНАЛЬНО их доле в общей
      стоимости приёма — так сумма по всем услугам/врачам в итоге сходится к
      реальной собранной выручке, а не показывает только "первую" услугу
      приёма или гадает.
    - historyRows — таблица последних начислений/расходов за месяц (не
      только агрегированные суммы)."""
    from collections import defaultdict
    from datetime import timedelta
    from django.db.models import Sum
    from django.utils import timezone
    from apps.finance.models import Payment, Expense, PaymentAllocation
    from apps.treatments.models import TreatmentCure

    today = timezone.localdate()
    month_start = today.replace(day=1)
    month_label = today.strftime("%m.%Y")

    revenue = float(Payment.objects.filter(
        created_at__date__gte=month_start, type=Payment.TYPE_INCOME,
    ).aggregate(s=Sum("amount"))["s"] or 0)
    refunds = float(Payment.objects.filter(
        created_at__date__gte=month_start, type=Payment.TYPE_REFUND,
    ).aggregate(s=Sum("amount"))["s"] or 0)
    revenue_net = revenue - refunds

    by_category = (Expense.objects.filter(date__gte=month_start)
                   .values("category__name").annotate(total=Sum("amount")).order_by("-total"))
    expense_lines = [{"name": row["category__name"] or "Без категории", "amount": float(row["total"])} for row in by_category]
    expenses_total = sum(line["amount"] for line in expense_lines)
    profit = revenue_net - expenses_total

    # ── График по дням месяца ──
    daily_revenue = defaultdict(float)
    for row in (Payment.objects.filter(created_at__date__gte=month_start)
                .values("created_at__date", "type").annotate(s=Sum("amount"))):
        sign = 1 if row["type"] == Payment.TYPE_INCOME else -1
        daily_revenue[row["created_at__date"]] += sign * float(row["s"])
    daily_expenses = defaultdict(float)
    for row in Expense.objects.filter(date__gte=month_start).values("date").annotate(s=Sum("amount")):
        daily_expenses[row["date"]] += float(row["s"])
    daily_series = []
    d = month_start
    while d <= today:
        daily_series.append({
            "date": d.strftime("%d.%m"),
            "revenue": round(daily_revenue.get(d, 0)),
            "expenses": round(daily_expenses.get(d, 0)),
        })
        d += timedelta(days=1)

    # ── Разбивка выручки по услугам/врачам ──
    allocations = (PaymentAllocation.objects
                   .filter(payment__created_at__date__gte=month_start, payment__type=Payment.TYPE_INCOME,
                           payment__clinic=clinic)
                   .select_related("treatment"))
    treatment_ids = {a.treatment_id for a in allocations}
    cures_by_treatment = defaultdict(list)
    for c in TreatmentCure.objects.filter(treatment_id__in=treatment_ids).select_related("service", "doctor"):
        billed = float(c.price) * c.quantity * (1 - float(c.discount) / 100)
        cures_by_treatment[c.treatment_id].append((c, billed))
    revenue_by_service = defaultdict(float)
    revenue_by_doctor = defaultdict(float)
    for alloc in allocations:
        cures = cures_by_treatment.get(alloc.treatment_id) or []
        total_billed = sum(b for _, b in cures)
        if not cures or total_billed <= 0:
            revenue_by_service["—"] += float(alloc.amount)
            revenue_by_doctor["—"] += float(alloc.amount)
            continue
        for cure, billed in cures:
            share = float(alloc.amount) * (billed / total_billed)
            revenue_by_service[cure.service.name] += share
            revenue_by_doctor[cure.doctor.name if cure.doctor else "—"] += share
    revenue_by_service_list = sorted(
        ({"name": k, "amount": round(v)} for k, v in revenue_by_service.items()),
        key=lambda x: -x["amount"])[:10]
    revenue_by_doctor_list = sorted(
        ({"name": k, "amount": round(v)} for k, v in revenue_by_doctor.items()),
        key=lambda x: -x["amount"])[:10]

    # ── История начислений/расходов за месяц (таблица) ──
    history_rows = []
    for p in (Payment.objects.filter(created_at__date__gte=month_start)
              .select_related("patient").order_by("-created_at")[:60]):
        history_rows.append({
            "date": timezone.localtime(p.created_at).strftime("%d.%m.%Y %H:%M"),
            "kind": "income" if p.type == Payment.TYPE_INCOME else "refund",
            "label": f"{'Оплата' if p.type == Payment.TYPE_INCOME else 'Возврат'} — {p.patient.full_name if p.patient else '—'}",
            "amount": float(p.amount) * (1 if p.type == Payment.TYPE_INCOME else -1),
            "sortKey": p.created_at,
        })
    for e in Expense.objects.filter(date__gte=month_start).select_related("category").order_by("-date")[:60]:
        history_rows.append({
            "date": e.date.strftime("%d.%m.%Y"),
            "kind": "expense",
            "label": f"Расход — {e.category.name if e.category else 'Без категории'}: {e.description or ''}".rstrip(": "),
            "amount": -float(e.amount),
            # sortKey сравнивается с Payment.created_at (timezone-aware, см.
            # выше) — обязательно тоже делаем aware, иначе сравнение naive/
            # aware datetime кидает TypeError при сортировке.
            "sortKey": timezone.make_aware(timezone.datetime.combine(e.date, timezone.datetime.min.time())),
        })
    history_rows.sort(key=lambda r: r["sortKey"], reverse=True)
    for r in history_rows:
        del r["sortKey"]
    history_rows = history_rows[:80]

    return {
        "monthLabel": month_label,
        "revenue": revenue_net,
        "expenseLines": expense_lines,
        "expensesTotal": expenses_total,
        "profit": profit,
        "marginPct": round(profit / revenue_net * 100, 1) if revenue_net else 0.0,
        "dailySeries": daily_series,
        "revenueByService": revenue_by_service_list,
        "revenueByDoctor": revenue_by_doctor_list,
        "historyRows": history_rows,
    }


def _newui_notifications_data(request):
    """Уведомления — полный список для /new/notifications/. Переиспользует ту
    же выборку, что и старый интерфейс (apps.notifications.views.
    _user_notifications — уже фильтрует по пользователю и текущей клинике),
    просто отдаёт плоским списком под оформление нового интерфейса:
    группировка по дням (Сегодня/Вчера/Ранее) и фильтр по типу — на клиенте,
    тем же паттерном, что и остальные таблицы/списки нового интерфейса.
    Пометка прочитанным/«прочитать всё» — существующие эндпоинты
    (/notifications/<id>/read/, /notifications/read-all/), с ними уже умеет
    работать сама модель уведомлений — дублировать не стали."""
    from django.utils import timezone
    from apps.notifications.views import _user_notifications

    qs = _user_notifications(request).select_related("actor").order_by("-created_at")[:200]
    return [
        {
            "id": n.pk,
            "title": n.title,
            "body": n.body,
            "type": n.type,
            "isRead": n.is_read,
            "link": n.link,
            "actor": n.actor.name if n.actor else "",
            "time": timezone.localtime(n.created_at).strftime("%d.%m.%Y %H:%M"),
        }
        for n in qs
    ]


def _newui_audit_data(clinic):
    """Журнал аудита — реальная история изменений (django-simple-history) по
    пациентам и приёмам лечения, плюс факты приёма оплат/возвратов (Payment —
    без HistoricalRecords, поэтому только события создания, без отката: у
    платежа нет хранимого «предыдущего состояния», в отличие от пациента/
    приёма). Входы в систему по-прежнему не логируются — честно ограничиваем
    раздел тем, что реально есть.

    historyId/model/canRevert — нужны фронтенду для кнопки отката (только
    суперадминистратору, см. apps.users.newui_views.audit_revert): откатить
    можно только запись пациента/приёма с реальной исторической записью
    (history_type != "-" — до состояния удаления откатывать через эту кнопку
    смысла нет, там нет корректного «предыдущего» состояния объекта)."""
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    from apps.finance.models import Payment
    from django.utils import timezone

    if not clinic:
        return []
    events = []
    for h in (Patient.history.filter(clinic=clinic)
              .select_related("history_user").order_by("-history_date")[:60]):
        # Историческая модель simple_history — отдельный класс с копией полей,
        # без кастомных @property исходной модели (full_name и т.п.) — собираем вручную.
        name = " ".join(p for p in (h.last_name, h.first_name, h.middle_name) if p)
        events.append({
            "time": timezone.localtime(h.history_date).strftime("%d.%m.%Y %H:%M"),
            "user": h.history_user.name if h.history_user else "—",
            "action": {"+": "Создание", "~": "Изменение", "-": "Удаление"}.get(h.history_type, h.history_type),
            "object": f"Пациент — {name}",
            "model": "patient", "historyId": h.history_id, "canRevert": h.history_type != "-",
            "sortKey": h.history_date,
        })
    for h in (Treatment.history.filter(clinic=clinic)
              .select_related("history_user").order_by("-history_date")[:60]):
        events.append({
            "time": timezone.localtime(h.history_date).strftime("%d.%m.%Y %H:%M"),
            "user": h.history_user.name if h.history_user else "—",
            "action": {"+": "Создание", "~": "Изменение", "-": "Удаление"}.get(h.history_type, h.history_type),
            "object": f"Приём №{h.number or h.pk} — {h.get_status_display()}",
            "model": "treatment", "historyId": h.history_id, "canRevert": h.history_type != "-",
            "sortKey": h.history_date,
        })
    for p in (Payment.objects.filter(clinic=clinic)
              .select_related("patient", "received_by").order_by("-created_at")[:60]):
        method_label = dict(Payment.METHOD_CHOICES).get(p.method, p.method)
        type_label = dict(Payment.TYPE_CHOICES).get(p.type, p.type)
        events.append({
            "time": timezone.localtime(p.created_at).strftime("%d.%m.%Y %H:%M"),
            "user": p.received_by.name if p.received_by else "—",
            "action": type_label,
            "object": f"{p.patient.full_name if p.patient else '—'} — {round(p.amount)} сом ({method_label})",
            "model": "payment", "historyId": None, "canRevert": False,
            "sortKey": p.created_at,
        })
    events.sort(key=lambda e: e["sortKey"], reverse=True)
    for e in events:
        del e["sortKey"]
    return events[:80]


def _newui_settings_data(clinic):
    """Настройки клиники — те же реальные поля ClinicSettings/Clinic.timezone,
    что и старый /settings/ (apps.settings_clinic.views.settings_view), просто
    подмножество (общие + контакты/реквизиты) в дизайне нового интерфейса.
    Подключение WhatsApp/Telegram (QR/webhook) — отдельные страницы, ведём
    туда же, что и старый интерфейс (/notifications/wa-connect/, /tg-connect/)."""
    from apps.settings_clinic.models import ClinicSettings
    from apps.users.models import TIMEZONE_CHOICES
    from .models_salary import DoctorSchedule

    cs = ClinicSettings.get()
    return {
        # Поля формы ClinicSettingsForm, для которых в новом интерфейсе пока
        # нет своего элемента управления — передаём как есть, чтобы форма
        # сохранения (POST всех полей формы разом, как и старый /settings/)
        # их не затёрла пустыми/выключенными значениями.
        "currency": cs.currency,
        "currencySecondary": cs.currency_secondary,
        "currencyChoices": [{"code": c, "label": lbl} for c, lbl in ClinicSettings.CURRENCY_CHOICES],
        "telegramBotToken": cs.telegram_bot_token,
        "requireUniquePhone": cs.require_unique_phone,
        "visitsJournalStaff": cs.visits_journal_staff,
        "appointmentSlot": cs.appointment_slot,
        "language": cs.language,
        "timezone": getattr(clinic, "timezone", "Asia/Bishkek"),
        "timezoneChoices": [{"code": c, "label": lbl} for c, lbl in TIMEZONE_CHOICES],
        "name": cs.name,
        "phone": cs.phone,
        "address": cs.address,
        "receiptFormat": cs.receipt_format,
        "receiptFormatChoices": [{"code": c, "label": lbl} for c, lbl in ClinicSettings.RECEIPT_FORMAT_CHOICES],
        "receiptClinicName": cs.receipt_clinic_name,
        "receiptLegalName": cs.receipt_legal_name,
        "receiptInn": cs.receipt_inn,
        "receiptAddress": cs.receipt_address,
        "warrantyTerms": cs.warranty_terms,
        "waEnabled": cs.wa_enabled,
        "waRemindDay": cs.wa_remind_day,
        "waRemindHour": cs.wa_remind_hour,
        "waRemindDebtDays": cs.wa_remind_debt_days,
        "telegramEnabled": cs.telegram_enabled,
        "telegramBotUsername": cs.telegram_bot_username,
        # «Кабинеты и график» (вкладка настроек) — реальные данные, сохранение
        # идёт через уже существующие эндпоинты старого интерфейса
        # (/users/branches/.../cabinets/add/, /users/cabinets/.../delete/,
        # /users/schedule/.../edit/ — см. apps.users.views.cabinet_create и
        # соседние), просто вызываются через fetch() и перерисовывают эту же
        # страницу (см. postForm/flashAndReload в base.html), а не уводят на
        # старый интерфейс.
        "branches": [
            {
                "id": b.pk, "name": b.name,
                "cabinets": [
                    {"id": c.pk, "name": c.name, "color": c.color}
                    for c in b.cabinets.filter(is_active=True).order_by("name")
                ],
            }
            for b in Branch.objects.all()
        ],
        "scheduleDays": [{"num": num, "label": label} for num, label in DoctorSchedule.DAY_CHOICES],
        "doctorSchedules": _newui_doctor_schedules(clinic),
        # «Причины отмены» и «Страховые компании» — тоже реальные справочники
        # (apps.appointments.models.CancellationReason, apps.patients.models_insurance.
        # InsuranceCompany), уже управляемые в старом интерфейсе через общий
        # /settings/references/<kind>/... (apps.settings_clinic.views.reference_add/
        # reference_delete) — переиспользуем те же эндпоинты, просто с плоским
        # списком «имя» вместо всей карточки старого интерфейса.
        "cancelReasons": _newui_reference_list("cancel_reasons"),
        "insuranceCompanies": _newui_reference_list("insurance"),
    }


def _newui_reference_list(kind):
    from apps.settings_clinic.views import _ref_models
    Model, _label, _icon = _ref_models()[kind]
    return [{"id": obj.pk, "name": str(obj)} for obj in Model.objects.all()]


def _newui_doctor_schedules(clinic):
    """Врачи клиники + их рабочий график по дням недели, для вкладки
    «Кабинеты и график» в Настройках нового интерфейса."""
    from .models import clinic_doctors
    from .models_salary import DoctorSchedule

    doctors = clinic_doctors(clinic).order_by("name").prefetch_related("schedules")
    rows = []
    for doc in doctors:
        by_day = {s.day_of_week: s for s in doc.schedules.all()}
        rows.append({
            "id": doc.pk, "name": doc.name,
            "branchId": next((s.branch_id for s in by_day.values()), None),
            "days": [
                {
                    "num": num,
                    "working": num in by_day,
                    "start": by_day[num].start_time.strftime("%H:%M") if num in by_day else "09:00",
                    "end": by_day[num].end_time.strftime("%H:%M") if num in by_day else "18:00",
                }
                for num, _label in DoctorSchedule.DAY_CHOICES
            ],
        })
    return rows


def _newui_funnel_data(clinic):
    """CRM-воронка заявок («Заявки · CRM») — раздел, которого раньше не было
    вообще нигде в системе (ни в старом интерфейсе). Реальная модель
    apps.patients.models.Lead, создана специально для этого раздела."""
    from apps.patients.models import Lead, LeadSource
    from apps.users.models import clinic_staff

    leads = list(Lead.objects.filter(clinic=clinic).select_related("source", "assigned_to")) if clinic else []
    return {
        "leads": [{
            "id": l.pk, "name": l.name, "phone": l.phone,
            "sourceId": l.source_id, "sourceName": l.source.name if l.source else "",
            "stage": l.stage, "comment": l.comment,
            "assignedToId": l.assigned_to_id, "assignedToName": l.assigned_to.name if l.assigned_to else "",
            "patientId": l.patient_id,
        } for l in leads],
        "stages": [{"code": c, "label": lbl} for c, lbl in Lead.STAGE_CHOICES],
        "sourceOptions": [{"id": s.pk, "name": s.name} for s in LeadSource.objects.filter(is_active=True).order_by("name")],
        "staffOptions": [{"id": u.pk, "name": u.name} for u in (clinic_staff(clinic).order_by("name") if clinic else [])],
    }


def _newui_cashdesk_data(request, clinic):
    """Касса — реальная кассовая смена (apps.finance.models.CashShift) и
    реальная очередь ожидающих оплат: уведомления, отправленные врачами
    через send_to_cashier (apps.finance.views.send_to_cashier), тому же
    механизму, что уже используется в старом интерфейсе."""
    from urllib.parse import urlparse, parse_qs
    from django.utils import timezone
    from apps.finance.models import CashShift, Payment
    from apps.notifications.models import Notification
    from apps.patients.models import Patient

    branch = None
    if clinic:
        from apps.users.models import Branch
        branch = Branch.objects.filter(clinic=clinic, is_main=True).first() or Branch.objects.filter(clinic=clinic).first()

    shift = CashShift.objects.filter(branch=branch, status=CashShift.STATUS_OPEN).first() if branch else None
    shift_data = None
    if shift:
        z = shift.z_report()
        shift_data = {
            "id": shift.pk,
            "openedAt": timezone.localtime(shift.opened_at).strftime("%d.%m.%Y %H:%M"),
            "openedBy": shift.opened_by.name if shift.opened_by else "—",
            "openingCash": float(shift.opening_cash),
            "byMethod": {code: float(z["byMethod"].get(code, 0)) for code, _ in Payment.METHOD_CHOICES},
            "incomeTotal": float(z["incomeTotal"]),
            "refundTotal": float(z["refundTotal"]),
            "expectedCash": float(z["expectedCash"]),
        }

    # send_to_cashier рассылает одно Notification на КАЖДОГО админа клиники
    # (fan-out) — раньше очередь фильтровалась строго по user=request.user,
    # поэтому другие администраторы не видели уже отправленные заявки
    # ("после отправки в кассу — в кассе ничего нет"). Показываем общую
    # очередь по клинике и схлопываем дубли fan-out по link (одна заявка =
    # одна строка, кто бы её ни принял — см. cashdesk_queue_dismiss).
    # type="payment" покрывает и «примите оплату» (send_to_cashier, link вида
    # /finance/payments/?patient=..) и «оплата принята» — просто уведомление
    # без действия (apps.finance.views._notify_cashier_payment, link без
    # query-строки), которое иначе после каждого «Принято» тут же
    # воскрешало бы ту же заявку в очереди. В очередь берём только первое.
    # Раньше строка заявки бралась готовым текстом (n.body), собранным на
    # сервере через Django _() — по факту без скомпилированных .mo-каталогов
    # для uz/ky это никогда не переводилось и всегда оставалось на русском,
    # даже когда весь остальной интерфейс на узбекском (жалоба: «интерфейс на
    # узбекском, а сообщения в очереди на русском»). Вместо готового текста
    # отдаём сырые поля — фразу собирает JS через тот же t()-словарь, что и
    # остальной интерфейс (см. renderCashQueue в base.html).
    queue = []
    seen_links = set()
    qset = Notification.objects.filter(type="payment", is_read=False, link__startswith="/finance/payments/?patient=")
    qset = qset.filter(clinic=clinic) if clinic else qset.filter(user=request.user)
    raw_items = []
    for n in qset.select_related("actor").order_by("-created_at")[:100]:
        if n.link and n.link in seen_links:
            continue
        if n.link:
            seen_links.add(n.link)
        raw_items.append(n)
        if len(raw_items) >= 30:
            break
    pat_ids = set()
    treat_ids = set()
    parsed = []
    for n in raw_items:
        qs = parse_qs(urlparse(n.link or "").query)
        pid = int(qs["patient"][0]) if qs.get("patient") else None
        tid = int(qs["treatment"][0]) if qs.get("treatment") else None
        if pid: pat_ids.add(pid)
        if tid: treat_ids.add(tid)
        parsed.append((n, pid, tid, qs.get("amount", [""])[0]))
    pat_map = {p.pk: p for p in Patient.objects.filter(pk__in=pat_ids)} if pat_ids else {}
    from apps.treatments.models import Treatment as _Treatment
    treat_map = {t.pk: t for t in _Treatment.objects.filter(pk__in=treat_ids)} if treat_ids else {}
    for n, pid, tid, amount in parsed:
        pat = pat_map.get(pid)
        tr = treat_map.get(tid)
        queue.append({
            "id": n.pk,
            "patientId": pid,
            "patientName": pat.full_name if pat else "",
            "debt": float(pat.debt) if pat else 0,
            "treatmentId": tid,
            "treatmentNumber": tr.display_number if tr else None,
            "amount": amount,
            "from": n.actor.name if n.actor else "—",
            "time": timezone.localtime(n.created_at).strftime("%d.%m %H:%M"),
            "link": n.link,
        })

    # ── «Пациенты на сегодня» — реальные приёмы сегодня с непогашенным долгом
    # по приёму (Treatment.appointment), сгруппированные по пациенту (если у
    # пациента сегодня несколько приёмов — все его неоплаченные позиции идут
    # одной карточкой, кассир может отметить, за какие принимает оплату).
    # Приём без привязанного Treatment (лечение ещё не начато/не заведено) —
    # платить пока не за что, в список не попадает.
    from collections import defaultdict
    from apps.appointments.models import Appointment
    from apps.treatments.models import Treatment

    today = timezone.localdate()
    today_appts = list(
        Appointment.objects.filter(start_at__date=today)
        .exclude(status=Appointment.STATUS_CANCELLED)
        .select_related("patient").order_by("start_at")
    )
    appt_ids = [a.pk for a in today_appts]
    treat_by_appt = defaultdict(list)
    for tr in (Treatment.objects.filter(appointment_id__in=appt_ids)
               .exclude(status__in=(Treatment.STATUS_CANCELLED, Treatment.STATUS_DRAFT))
               .select_related("patient").prefetch_related("cures__service")):
        treat_by_appt[tr.appointment_id].append(tr)

    appts_by_patient = defaultdict(list)
    for a in today_appts:
        if a.patient_id:
            appts_by_patient[a.patient_id].append(a)

    today_patients = []
    for patient_id, appts in appts_by_patient.items():
        treatments = [tr for a in appts for tr in treat_by_appt.get(a.pk, [])]
        if not treatments:
            continue
        items = []
        for tr in treatments:
            services = ", ".join(c.service.name for c in tr.cures.all())
            debt = float(tr.debt)
            if debt > 0:
                items.append({"id": tr.pk, "desc": services or tr.get_status_display(), "amount": debt})
        today_patients.append({
            "patientId": patient_id,
            "patient": appts[0].patient.full_name,
            "time": timezone.localtime(min(a.start_at for a in appts)).strftime("%H:%M"),
            "items": items,
            "paid": len(items) == 0,
        })
    today_patients.sort(key=lambda p: p["time"])

    # ── «Оплаты» — вкладка для просмотра и повторной выдачи чека (payment_receipt,
    # apps.finance.views уже умеет печать/переоткрытие чека по Payment.pk — тут
    # просто список последних платежей, без нового бэкенда для самой печати). ──
    payments_qs = Payment.objects.select_related("patient", "received_by").order_by("-created_at")
    if branch:
        payments_qs = payments_qs.filter(branch=branch)
    recent_payments = [{
        "id": pm.pk,
        "patientId": pm.patient_id,
        "patientName": pm.patient.full_name if pm.patient_id else "—",
        "amount": float(pm.amount),
        "method": pm.get_method_display(),
        "type": pm.get_type_display(),
        "isRefund": pm.type == Payment.TYPE_REFUND,
        "receivedBy": pm.received_by.name if pm.received_by else "—",
        "time": timezone.localtime(pm.created_at).strftime("%d.%m.%Y %H:%M"),
    } for pm in payments_qs[:200]]

    return {
        "shift": shift_data, "queue": queue, "branchId": branch.pk if branch else None,
        "todayPatients": today_patients, "payments": recent_payments,
    }


def _newui_messages_data(clinic):
    """Список бесед WhatsApp/Telegram для нового интерфейса — та же выборка
    (сгруппировать WaMessage по пациенту, взять последнее сообщение и счётчик
    непрочитанных), что и apps.notifications.views.wa_inbox. Сама переписка
    по конкретному пациенту грузится на лету через patient_wa_messages,
    отправка — через тот же patient_notify, что и старый интерфейс."""
    from django.utils import timezone
    from apps.notifications.models import WaMessage
    from apps.notifications.whatsapp import wa_enabled
    from apps.notifications.telegram import tg_enabled

    base = WaMessage.all_clinics.exclude(patient__isnull=True)
    if clinic:
        base = base.filter(clinic=clinic)
    convos = {}
    for m in base.select_related("patient").order_by("-id")[:2000]:
        c = convos.get(m.patient_id)
        if c is None:
            c = convos[m.patient_id] = {"patient": m.patient, "last": m, "unread": 0}
        if m.direction == "in" and not m.read:
            c["unread"] += 1
    rows = sorted(convos.values(), key=lambda c: c["last"].created_at, reverse=True)
    clients = [{
        "id": c["patient"].pk,
        "name": c["patient"].full_name,
        "phone": c["patient"].phone,
        "channel": "whatsapp" if c["last"].channel == WaMessage.CH_WA else "telegram",
        "lastBody": c["last"].body or ("[медиа]" if c["last"].media_file else ""),
        "lastTime": timezone.localtime(c["last"].created_at).strftime("%d.%m %H:%M"),
        "unread": c["unread"],
    } for c in rows[:150]]
    return {"clients": clients, "waEnabled": wa_enabled(), "tgEnabled": tg_enabled()}


def _newui_patientcard_detail_data(patient):
    """Вкладки карточки пациента (История приёмов/Зубная карта/План лечения/
    Финансы/Документы) нового интерфейса — те же запросы, что и старый
    apps.patients.views.patient_detail (apps/patients/views.py:393+), просто
    сериализованы в JSON вместо серверного рендера в шаблон."""
    from decimal import Decimal
    from django.db.models import Q
    from django.utils import timezone
    from apps.finance.models import Payment
    from apps.treatments.models import Treatment, TreatmentFile
    from apps.treatments.models_teeth import ToothCondition
    from apps.treatments.models_plan import TreatmentPlan

    status_pill = {
        Treatment.STATUS_DRAFT: "grey", Treatment.STATUS_PLANNED: "cobalt",
        Treatment.STATUS_IN_PROGRESS: "amber", Treatment.STATUS_COMPLETED: "teal",
        Treatment.STATUS_CANCELLED: "coral", Treatment.STATUS_PAID: "teal",
    }
    treatments = list(
        Treatment.all_objects.filter(patient=patient, is_deleted=False)
        .select_related("doctor").prefetch_related("cures__service").order_by("-created_at")[:100]
    )
    history = []
    for t in treatments:
        services = ", ".join(c.service.name for c in t.cures.all()) or "—"
        history.append({
            "id": t.pk,
            "date": timezone.localtime(t.created_at).strftime("%d.%m.%Y"),
            "service": services,
            "doctor": t.doctor.name if t.doctor else "—",
            "amount": float(t.total_amount),
            "status": t.get_status_display(),
            "statusColor": status_pill.get(t.status, "cobalt"),
            "needsConfirmation": t.needs_doctor_confirmation,
        })

    plan_status_pill = {"draft": "grey", "approved": "cobalt", "in_progress": "amber", "completed": "teal", "cancelled": "coral"}
    plans = []
    for p in (TreatmentPlan.objects.filter(patient=patient)
              .select_related("doctor").prefetch_related("stages").order_by("-created_at")[:50]):
        stage_titles = [s.title for s in p.stages.all() if s.title]
        plans.append({
            "id": p.pk,
            "stage": stage_titles[0] if stage_titles else p.title,
            "doctor": p.doctor.name if p.doctor else "—",
            "completionPct": p.completion_pct,
            "totalPrice": float(p.total_price),
            "status": p.get_status_display(),
            "statusCode": p.status,
        })

    payments_qs = Payment.all_clinics.filter(patient=patient).select_related("received_by").order_by("-created_at")
    payments = [{
        "id": pm.pk,
        "date": timezone.localtime(pm.created_at).strftime("%d.%m.%Y"),
        "purpose": "Возврат" if pm.type == Payment.TYPE_REFUND else "Оплата",
        "method": pm.get_method_display(),
        "amount": float(pm.amount) * (-1 if pm.type == Payment.TYPE_REFUND else 1),
    } for pm in payments_qs[:100]]
    total_paid = sum((pm["amount"] for pm in payments if pm["amount"] > 0), 0.0)

    from apps.treatments.models_teeth import REAL_TO_JS_TOOTH_CODE, ToothSurfaceCondition, ToothGumCondition
    tooth_conditions = {}
    for tc in ToothCondition.objects.filter(patient=patient).select_related("status"):
        prefix = "baby" if tc.tooth_number >= 51 else "adult"
        if tc.status:
            tooth_conditions[f"{prefix}-{tc.tooth_number}"] = REAL_TO_JS_TOOTH_CODE.get(tc.status.code, "norma")
    # коды в БД совпадают с JS 1:1 (см. apps/treatments/models_teeth.py) — без маппинга
    tooth_surface_conditions = {}
    for sc in ToothSurfaceCondition.objects.filter(patient=patient).select_related("status"):
        if sc.status:
            prefix = "baby" if sc.tooth_number >= 51 else "adult"
            tooth_surface_conditions[f"{prefix}-{sc.tooth_number}-s{sc.surface_index}"] = sc.status.code
    tooth_gum_conditions = {}
    for gc in ToothGumCondition.objects.filter(patient=patient).select_related("status"):
        if gc.status:
            prefix = "baby" if gc.tooth_number >= 51 else "adult"
            tooth_gum_conditions[f"{prefix}-{gc.tooth_number}"] = gc.status.code

    kind_labels = dict(TreatmentFile.KIND_CHOICES)
    # Файлы приёмов (treatment__patient=patient) + загруженные напрямую из
    # вкладки «Документы» карты пациента, вне контекста конкретного визита
    # (patient=patient, treatment пуст — см. apps.patients.views.patient_file_upload).
    documents = [{
        "id": f.pk,
        "name": f.name,
        "kind": kind_labels.get(f.kind, f.kind),
        "url": f.file.url,
        "date": timezone.localtime(f.uploaded_at).strftime("%d.%m.%Y"),
    } for f in (TreatmentFile.objects.filter(Q(treatment__patient=patient) | Q(patient=patient))
                .select_related("treatment").order_by("-uploaded_at")[:100])]

    return {
        "history": history,
        "plans": plans,
        "payments": payments,
        "totalPaid": total_paid,
        "toothConditions": tooth_conditions,
        "toothSurfaceConditions": tooth_surface_conditions,
        "toothGumConditions": tooth_gum_conditions,
        "documents": documents,
        "fileKinds": [{"code": k, "label": lbl} for k, lbl in TreatmentFile.KIND_CHOICES],
    }


def initials_of(name):
    parts = (name or "").split()
    return "".join(p[0] for p in parts[:2]).upper()


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
            # филиал + (опционально) автозаполнение услуг/материалов/ЭМК/документов в новой клинике
            do_seed = request.POST.get("clinic_seed", "1") != "0"
            set_current_clinic(new_clinic)
            try:
                Branch.objects.create(name=cname, address="—", phone="—", is_main=True)
                res = seed_dental() if do_seed else None
            finally:
                clear_current_clinic()
            if res:
                messages.success(request, _(
                    "Клиника «%(n)s» создана. Админ: %(l)s. Заполнено: услуг %(s)s, материалов %(m)s, ЭМК %(e)s, документов %(d)s"
                ) % {"n": cname, "l": alogin, "s": res["services"], "m": res["materials"],
                     "e": res.get("emr", 0), "d": res.get("docs", 0)})
            else:
                messages.success(request, _(
                    "Клиника «%(n)s» создана пустой (без демо-данных). Админ: %(l)s"
                ) % {"n": cname, "l": alogin})
            # Данные доступа для передачи новой клинике — одноразовый показ через сессию
            # (пароль в открытом виде доступен только сейчас, до хеширования уже не достать).
            from django.conf import settings as dj_settings
            app_host = getattr(dj_settings, "APP_HOST", "app.sadaf.kg")
            request.session["new_clinic_ready"] = {
                "name": cname, "login": alogin, "password": apass, "slug": slug,
                "login_url": f"https://{app_host}/login/?clinic={slug}",
            }
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
        "new_clinic_ready": request.session.pop("new_clinic_ready", None),
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
    from apps.services.models import Service
    from apps.tasks.models import Task
    return {
        "patient": (Patient, "Пациенты"),
        "treatment": (Treatment, "Приёмы"),
        "appointment": (Appointment, "Записи"),
        "service": (Service, "Услуги"),
        "task": (Task, "Задачи"),
    }


def _recycle_qs(Model):
    """Удалённые записи ТЕКУЩЕЙ клиники (изоляция корзины между клиниками)."""
    from apps.tenancy import get_current_clinic
    qs = Model.all_objects.filter(is_deleted=True)
    clinic = get_current_clinic()
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    return qs


def _recycle_bin_allowed(user):
    """Корзина изначально скрыта ото ВСЕГО РЯДОВОГО ПЕРСОНАЛА (в отличие от
    журнала посещений, который по умолчанию виден) — включается явно в
    настройках клиники (ClinicSettings.recycle_bin_staff) тем же
    superadmin/admin_main, которые сами видят корзину всегда (иначе — тупик:
    директор не смог бы дойти до кнопки-переключателя, если бы сам себе
    закрыл доступ по умолчанию). Обычная роль «Админ» (не admin_main) —
    подчиняется тумблеру, как и остальной персонал."""
    if user.is_superadmin or user.is_admin_main:
        return True
    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()
    return bool(getattr(cs, "recycle_bin_staff", False))


@login_required
@role_required("superadmin", "admin_main", "admin")
def recycle_bin(request):
    if not _recycle_bin_allowed(request.user):
        messages.error(request, "Корзина скрыта администратором")
        return redirect("/")
    # Тот же паттерн переключателя видимости, что и у apps.patients.views.
    # visits_journal (action=toggle_visibility) — только superadmin/admin_main
    # решают, включать ли корзину рядовому персоналу.
    if request.method == "POST" and request.POST.get("action") == "toggle_visibility":
        if request.user.is_superadmin or request.user.is_admin_main:
            from apps.settings_clinic.models import ClinicSettings
            cs = ClinicSettings.get()
            cs.recycle_bin_staff = not cs.recycle_bin_staff
            cs.save(update_fields=["recycle_bin_staff", "updated_at"])
        return redirect("recycle_bin")
    models = _recycle_models()
    current = request.GET.get("kind", "")
    items, counts = [], {}
    for kind, (Model, label) in models.items():
        qs = _recycle_qs(Model)
        counts[kind] = qs.count()
        if current and current != kind:
            continue
        for obj in qs.order_by("-deleted_at")[:300]:
            items.append({
                "kind": kind, "label": label, "pk": obj.pk,
                "title": str(obj), "deleted_at": obj.deleted_at,
                "deleted_by": obj.deleted_by,
            })
    items.sort(key=lambda x: x["deleted_at"] or 0, reverse=True)
    cats = [{"kind": k, "label": models[k][1], "count": counts.get(k, 0)} for k in models]
    return render(request, "users/recycle_bin.html", {
        "items": items, "cats": cats, "current_kind": current,
        "total": sum(counts.values()),
    })


@login_required
@role_required("superadmin", "admin_main", "admin")
@require_POST
def recycle_restore(request, kind, pk):
    models = _recycle_models()
    if kind in models:
        Model = models[kind][0]
        obj = get_object_or_404(_recycle_qs(Model), pk=pk)
        obj.restore()
        messages.success(request, _("Восстановлено: %(t)s") % {"t": str(obj)})
    return redirect("recycle_bin")


def _purge_summary(kind, obj):
    """Сводка связанных данных, которые будут удалены вместе с объектом."""
    if kind == "patient" and hasattr(obj, "related_summary"):
        s = obj.related_summary()
        rows = [
            ("Приёмы (лечения)", s["treatments"]),
            ("Планы лечения", s["plans"]),
            ("Платежи", s["payments"]),
            ("Авансы", s["advances"]),
            ("Назначения лекарств", s["medicines"]),
            ("Записи в календаре", s["appointments"]),
        ]
        return [(label, n) for label, n in rows if n], s.get("debt")
    return [], None


@login_required
@role_required("superadmin", "admin_main")
def recycle_purge_confirm(request, kind, pk):
    """Страница-предупреждение перед безвозвратным удалением: что именно удалится."""
    models = _recycle_models()
    if kind not in models:
        return redirect("recycle_bin")
    Model = models[kind][0]
    obj = get_object_or_404(_recycle_qs(Model), pk=pk)
    related, debt = _purge_summary(kind, obj)
    return render(request, "users/recycle_purge_confirm.html", {
        "kind": kind, "obj": obj, "title": str(obj),
        "related": related, "debt": debt, "label": models[kind][1],
    })


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def recycle_purge(request, kind, pk):
    from django.db.models import ProtectedError
    models = _recycle_models()
    if kind in models:
        Model = models[kind][0]
        obj = get_object_or_404(_recycle_qs(Model), pk=pk)
        title = str(obj)
        try:
            if kind == "patient" and hasattr(obj, "purge_with_related"):
                obj.purge_with_related()   # каскадно: приёмы, платежи, планы и т.д.
            else:
                obj.delete()   # безвозвратно
            messages.success(request, _("Удалено безвозвратно: %(t)s") % {"t": title})
        except ProtectedError:
            messages.error(request, _("Нельзя удалить «%(t)s»: есть связанные записи.") % {"t": title})
    return redirect("recycle_bin")


# ─── Обзор клиники + персональные доступы ────────────────────────────────────

def _can_manage_access(actor, target):
    """Кто может менять доступы сотрудника: суперадмин — любого; гл.админ — своих
    (не себя, не суперадмина)."""
    if actor.is_superadmin:
        return True
    if (actor.is_admin_main and target.clinic_id == actor.clinic_id
            and target.pk != actor.pk and not target.is_superadmin):
        return True
    return False


def _apply_access_from_form(actor, target, form):
    """Сохранить персональные доступы из формы сотрудника (full_access + sections).
    Применяется только если actor имеет право менять доступы target."""
    from apps.users.models import SECTION_KEYS
    if not _can_manage_access(actor, target):
        return
    if form.cleaned_data.get("full_access"):
        target.allowed_sections = None
    else:
        target.allowed_sections = [s for s in (form.cleaned_data.get("sections") or [])
                                   if s in SECTION_KEYS]
    target.save(update_fields=["allowed_sections"])


@login_required
def clinic_overview(request, clinic_id):
    """Сводка по клинике + управление доступами сотрудников.
    Доступ: суперадмин (любая клиника) или гл.администратор своей клиники."""
    from apps.users.models import Clinic, SECTIONS, SECTION_KEYS
    from apps.tenancy import unscoped
    from django.utils import timezone
    from django.db.models import Sum

    user = request.user
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    if not (user.is_superadmin or (user.is_admin_main and user.clinic_id == clinic.pk)):
        messages.error(request, _("Нет доступа к обзору этой клиники"))
        return redirect("/")

    stats = {"revenue": None}
    with unscoped():
        from apps.patients.models import Patient
        from apps.appointments.models import Appointment
        stats["patients"] = Patient.all_objects.filter(clinic_id=clinic.pk, is_deleted=False).count()
        appts = Appointment.all_objects.filter(clinic_id=clinic.pk, is_deleted=False)
        stats["appointments"] = appts.count()
        stats["appointments_today"] = appts.filter(start_at__date=timezone.localdate()).count()
        try:
            from apps.finance.models import Payment
            rev = Payment.all_clinics.filter(clinic_id=clinic.pk).aggregate(s=Sum("amount"))["s"]
            stats["revenue"] = rev or 0
        except Exception:
            pass

    staff = list(
        User.objects.filter(clinic_id=clinic.pk).select_related("role")
        .order_by("-is_active", "name")
    )
    all_keys = list(SECTION_KEYS)
    staff_data = []
    for s in staff:
        s.full_access = s.allowed_sections is None
        s.checked_sections = set(all_keys) if s.full_access else set(s.allowed_sections or [])
        s.manageable = _can_manage_access(user, s)
        staff_data.append({
            "pk": s.pk,
            "name": s.name,
            "login": s.login,
            "role": s.role.display_name if s.role else "",
            "active": s.is_active,
            "full": s.full_access,
            "sections": all_keys if s.full_access else list(s.checked_sections),
            "manageable": s.manageable,
        })
    stats["staff"] = len(staff)

    from apps.users.models import ClinicSite, TIMEZONE_CHOICES
    from apps.settings_clinic.models import ClinicSettings
    from django.conf import settings as dj_settings
    site, _c = ClinicSite.objects.get_or_create(clinic=clinic, defaults={"headline": clinic.name})
    public_url = "https://{}.{}".format(clinic.slug, getattr(dj_settings, "PUBLIC_BASE_DOMAIN", "denta.tw1.ru"))

    return render(request, "users/clinic_overview.html", {
        "clinic": clinic,
        "stats": stats,
        "staff": staff,
        "staff_data": staff_data,
        "sections": SECTIONS,
        "site": site,
        "public_url": public_url,
        "timezone_choices": TIMEZONE_CHOICES,
        "tariff_choices": ClinicSettings.TARIFF_CHOICES,
        "all_modules": ClinicSettings.ALL_MODULES,
        "grantable_access": Clinic.GRANTABLE_ACCESS,
        "clinic_access_set": set(clinic.granted_access or []),
        "editable_by_superadmin": user.is_superadmin,
    })


@login_required
@require_POST
def toggle_clinic_site(request, clinic_id):
    """Включить/выключить публичный сайт клиники — только суперадмин."""
    from apps.users.models import Clinic, ClinicSite
    if not request.user.is_superadmin:
        messages.error(request, _("Включать сайт может только суперадмин"))
        return redirect(request.META.get("HTTP_REFERER") or "/")
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    site, _c = ClinicSite.objects.get_or_create(clinic=clinic, defaults={"headline": clinic.name})
    site.enabled = not site.enabled
    site.save(update_fields=["enabled"])
    messages.success(request, _("Публичный сайт %(s)s") % {
        "s": "включён" if site.enabled else "выключен"})
    return redirect(request.META.get("HTTP_REFERER") or f"/users/clinic/{clinic_id}/overview/")


@login_required
@require_POST
def toggle_clinic_channel(request, clinic_id, channel):
    """Включить/выключить WhatsApp или Telegram для клиники — мастер-переключатель,
    доступен только суперадмину (по тарифу/лицензии), независимо от того, что
    настроено у самой клиники в ClinicSettings."""
    from apps.users.models import Clinic
    if not request.user.is_superadmin:
        messages.error(request, _("Доступно только суперадмину"))
        return redirect(request.META.get("HTTP_REFERER") or "/")
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    field = {"wa": "wa_master_enabled", "tg": "telegram_master_enabled"}.get(channel)
    if not field:
        return redirect(request.META.get("HTTP_REFERER") or "/")
    setattr(clinic, field, not getattr(clinic, field))
    clinic.save(update_fields=[field])
    label = "WhatsApp" if channel == "wa" else "Telegram"
    state = "включён" if getattr(clinic, field) else "выключен"
    messages.success(request, _("%(label)s для клиники %(state)s") % {"label": label, "state": state})
    return redirect(request.META.get("HTTP_REFERER") or f"/users/clinic/{clinic_id}/overview/")


@login_required
@require_POST
def clinic_update(request, clinic_id):
    """Редактировать ключевые поля клиники напрямую по её id — только
    суперадмин. Раньше тариф/модули можно было менять только для «текущей»
    (выбранной через «Войти →») клиники в сессии — неудобно; здесь то же
    самое, но по конкретному clinic_id, без обязательного «входа»."""
    from apps.users.models import Clinic
    if not request.user.is_superadmin:
        messages.error(request, _("Доступно только суперадмину"))
        return redirect(request.META.get("HTTP_REFERER") or "/")
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    name = request.POST.get("name", "").strip()
    if name:
        clinic.name = name
    slug = request.POST.get("slug", "").strip()
    if slug:
        clinic.slug = slug
    if request.POST.get("timezone"):
        clinic.timezone = request.POST["timezone"]
    clinic.tariff_plan = request.POST.get("tariff_plan", clinic.tariff_plan)
    until = request.POST.get("tariff_until", "").strip()
    if until:
        from datetime import datetime
        try:
            clinic.tariff_until = datetime.strptime(until, "%Y-%m-%d").date()
        except ValueError:
            pass
    else:
        clinic.tariff_until = None
    clinic.enabled_modules = request.POST.getlist("modules")
    clinic.save(update_fields=["name", "slug", "timezone", "tariff_plan", "tariff_until", "enabled_modules"])
    messages.success(request, _("Клиника «%(n)s» обновлена") % {"n": clinic.name})
    return redirect(request.META.get("HTTP_REFERER") or f"/users/clinic/{clinic_id}/overview/")


@login_required
@require_POST
def clinic_set_access(request, clinic_id):
    """Выдать/забрать клинике доступы, которые может менять только
    супер-админ (Clinic.granted_access, см. GRANTABLE_ACCESS)."""
    from apps.users.models import Clinic
    if not request.user.is_superadmin:
        messages.error(request, _("Доступно только суперадмину"))
        return redirect(request.META.get("HTTP_REFERER") or "/")
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    valid_keys = {key for key, _label in Clinic.GRANTABLE_ACCESS}
    selected = set(request.POST.getlist("access")) & valid_keys
    clinic.granted_access = sorted(selected)
    clinic.save(update_fields=["granted_access"])
    messages.success(request, _("Доступы клиники «%(n)s» обновлены") % {"n": clinic.name})
    return redirect(request.META.get("HTTP_REFERER") or f"/users/clinic/{clinic_id}/overview/")


def _can_edit_site(user, clinic):
    """Редактировать сайт: суперадмин (любую) или Директор своей клиники."""
    return user.is_superadmin or (user.is_admin_main and user.clinic_id == clinic.pk)


@login_required
def clinic_site_edit(request, clinic_id):
    """Конструктор публичного сайта клиники (суперадмин/Директор)."""
    from apps.users.models import Clinic, ClinicSite
    from django.conf import settings as dj_settings
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    if not _can_edit_site(request.user, clinic):
        messages.error(request, _("Нет доступа к редактированию сайта"))
        return redirect("/")
    site, _c = ClinicSite.objects.get_or_create(clinic=clinic, defaults={"headline": clinic.name})

    if request.method == "POST":
        text_fields = ["headline", "tagline", "about", "phone", "address", "hours",
                       "theme_color", "whatsapp", "instagram", "telegram",
                       "seo_title", "seo_description"]
        for f in text_fields:
            setattr(site, f, (request.POST.get(f) or "").strip())
        if not site.theme_color:
            site.theme_color = "#2563EB"
        # тумблеры (чекбокс присутствует = True)
        site.show_doctors = bool(request.POST.get("show_doctors"))
        site.show_services = bool(request.POST.get("show_services"))
        site.show_booking = bool(request.POST.get("show_booking"))
        site.published = bool(request.POST.get("published"))
        # изображения
        if request.FILES.get("logo"):
            site.logo = request.FILES["logo"]
        if request.FILES.get("cover"):
            site.cover = request.FILES["cover"]
        if request.POST.get("remove_logo"):
            site.logo = None
        if request.POST.get("remove_cover"):
            site.cover = None
        site.save()
        messages.success(request, _("Сайт сохранён"))
        return redirect(f"/users/clinic/{clinic_id}/site/")

    public_url = "https://{}.{}".format(clinic.slug, getattr(dj_settings, "PUBLIC_BASE_DOMAIN", "denta.tw1.ru"))
    return render(request, "users/site_edit.html", {
        "clinic": clinic, "site": site, "public_url": public_url,
    })


@login_required
def clinic_site_doctors(request, clinic_id):
    """Вкладка «Врачи и отзывы» конструктора сайта: профиль врача (специализация,
    стаж, телефон, биография, показ на сайте) + отзывы. Суперадмин / Директор."""
    from apps.users.models import Clinic, DoctorReview, clinic_doctors
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    if not _can_edit_site(request.user, clinic):
        messages.error(request, _("Нет доступа к редактированию сайта"))
        return redirect("/")

    if request.method == "POST":
        action = request.POST.get("action")
        doctor = clinic_doctors(clinic).filter(pk=request.POST.get("doctor_id")).first()
        if doctor is None:
            messages.error(request, _("Врач не найден"))
            return redirect(f"/users/clinic/{clinic_id}/site/doctors/")
        if action == "save_profile":
            doctor.specialty = (request.POST.get("specialty") or "").strip()[:150]
            doctor.bio = (request.POST.get("bio") or "").strip()
            doctor.phone = (request.POST.get("phone") or "").strip()[:30]
            try:
                exp = request.POST.get("experience_years")
                doctor.experience_years = int(exp) if exp not in (None, "") else None
            except (TypeError, ValueError):
                doctor.experience_years = None
            doctor.show_on_site = bool(request.POST.get("show_on_site"))
            update_fields = ["specialty", "bio", "phone", "experience_years", "show_on_site"]
            if request.FILES.get("avatar"):
                doctor.avatar = request.FILES["avatar"]
                update_fields.append("avatar")
            elif request.POST.get("remove_avatar"):
                doctor.avatar = None
                update_fields.append("avatar")
            doctor.save(update_fields=update_fields)
            messages.success(request, _("Профиль врача обновлён"))
        elif action == "add_review":
            text = (request.POST.get("text") or "").strip()
            author = (request.POST.get("author") or "").strip()[:150]
            if text and author:
                try:
                    rating = max(1, min(5, int(request.POST.get("rating") or 5)))
                except (TypeError, ValueError):
                    rating = 5
                DoctorReview.objects.create(doctor=doctor, author=author,
                                            rating=rating, text=text)
                messages.success(request, _("Отзыв добавлен"))
            else:
                messages.error(request, _("Укажите автора и текст отзыва"))
        elif action == "del_review":
            DoctorReview.objects.filter(pk=request.POST.get("review_id"), doctor=doctor).delete()
            messages.success(request, _("Отзыв удалён"))
        return redirect(f"/users/clinic/{clinic_id}/site/doctors/")

    from django.conf import settings as dj_settings
    doctors = list(clinic_doctors(clinic).prefetch_related("reviews"))
    public_url = "https://{}.{}".format(
        clinic.slug, getattr(dj_settings, "PUBLIC_BASE_DOMAIN", "denta.tw1.ru"))
    return render(request, "users/site_doctors.html", {
        "clinic": clinic, "doctors": doctors, "public_url": public_url,
    })


@login_required
@require_POST
def save_user_access(request, pk):
    """Сохранить персональные доступы сотрудника (из модала обзора клиники)."""
    from apps.users.models import SECTION_KEYS
    target = get_object_or_404(User, pk=pk)
    if not _can_manage_access(request.user, target):
        messages.error(request, _("Нет прав менять доступы этого сотрудника"))
        return redirect(request.META.get("HTTP_REFERER") or "/")

    target.is_active = not bool(request.POST.get("block_login"))
    if request.POST.get("full_access"):
        target.allowed_sections = None
    else:
        target.allowed_sections = [s for s in request.POST.getlist("sections") if s in SECTION_KEYS]
    target.save(update_fields=["allowed_sections", "is_active"])
    messages.success(request, _("Доступы сотрудника «%(n)s» обновлены") % {"n": target.name})
    return redirect(request.META.get("HTTP_REFERER")
                    or f"/users/clinic/{target.clinic_id}/overview/")


def _newui_profile_data(user):
    """Профиль для нового интерфейса — те же поля, что и старый /profile/
    (см. profile_view): ФИО/логин/пароль/аватар, номер WhatsApp, Google
    Calendar. Сохранение — тот же POST /profile/ (три ветки по маркерным
    полям _avatar_only/_whatsapp_only/основная форма) и /profile/daily-report/,
    просто вызываются через fetch() с новой страницы, как и везде раньше."""
    from apps.appointments.gcal import gcal_enabled
    gcal_account = getattr(user, "gcal_account", None)
    return {
        "name": user.name,
        "login": user.login,
        "phone": user.phone or "",
        "avatarUrl": user.avatar.url if user.avatar else "",
        "roleName": user.role.display_name if user.role else "",
        "gcalEnabled": gcal_enabled(),
        "gcalConnected": bool(gcal_account),
        "gcalEmail": getattr(gcal_account, "email", "") or "",
    }


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
        # Сохранение номера WhatsApp (отдельная мини-форма карточки)
        if "_whatsapp_only" in request.POST:
            user.phone = request.POST.get("phone", "").strip()
            user.save(update_fields=["phone"])
            messages.success(request, _("Номер WhatsApp сохранён"))
            return redirect("profile")
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
    from apps.appointments.gcal import gcal_enabled
    return render(request, "users/profile.html", {
        "profile_user": user,
        "gcal_enabled": gcal_enabled(),
        "gcal_account": getattr(user, "gcal_account", None),
    })


@require_POST
@login_required
def profile_send_daily_report(request):
    """Сформировать краткий отчёт за сегодня и отправить в WhatsApp текущему пользователю."""
    from datetime import date
    from django.db.models import Sum, Count
    from decimal import Decimal
    from apps.notifications.whatsapp import wa_send_text, wa_enabled
    from apps.appointments.models import Appointment
    from apps.finance.models import Payment
    from apps.patients.models import Patient

    user = request.user
    if not (user.phone or "").strip():
        messages.error(request, _("Укажите номер WhatsApp в профиле, чтобы получать отчёт"))
        return redirect("profile")
    if not wa_enabled():
        messages.error(request, _("WhatsApp не настроен (Green-API). Обратитесь к администратору."))
        return redirect("profile")

    today = date.today()
    appts = Appointment.objects.filter(start_at__date=today).exclude(
        status__in=[Appointment.STATUS_CANCELLED])
    appts_total = appts.count()
    completed = appts.filter(status=Appointment.STATUS_COMPLETED).count()
    payments_today = Payment.objects.filter(
        created_at__date=today, type=Payment.TYPE_INCOME).aggregate(
        s=Sum("amount"))["s"] or Decimal(0)
    new_patients = Patient.objects.filter(created_at__date=today).count()

    try:
        from apps.settings_clinic.models import ClinicSettings
        clinic_name = ClinicSettings.get().name
    except Exception:
        clinic_name = ""

    text = (
        "📊 *Ежедневный отчёт*\n"
        "%s\n"
        "📅 %s\n\n"
        "🗓 Записей сегодня: *%d*\n"
        "✅ Завершено приёмов: *%d*\n"
        "👤 Новых пациентов: *%d*\n"
        "💰 Поступления: *%s сом*"
    ) % (clinic_name, today.strftime("%d.%m.%Y"), appts_total, completed,
         new_patients, "{:,.0f}".format(payments_today).replace(",", " "))

    ok = wa_send_text(user.phone, text)
    if ok:
        messages.success(request, _("Отчёт отправлен в WhatsApp"))
    else:
        messages.error(request, _("Не удалось отправить отчёт. Проверьте настройки WhatsApp."))
    return redirect("profile")


# ─── Google Calendar OAuth ───────────────────────────────────────────────────
@login_required
def google_calendar_connect(request):
    """Старт OAuth: редирект на согласие Google."""
    from django.core import signing
    from apps.appointments.gcal import gcal_enabled, auth_url
    if not gcal_enabled():
        messages.error(request, _("Google Calendar не настроен. Обратитесь к администратору."))
        return redirect("profile")
    state = signing.dumps({"uid": request.user.pk}, salt="gcal-oauth")
    return redirect(auth_url(state))


@login_required
def google_calendar_callback(request):
    """Возврат от Google: обмен кода на токены, сохранение аккаунта."""
    from django.core import signing
    from apps.appointments.gcal import gcal_enabled, exchange_code, userinfo_email
    from apps.users.models import GoogleCalendarAccount
    from datetime import timedelta
    from django.utils import timezone

    if not gcal_enabled():
        return redirect("profile")
    err = request.GET.get("error")
    if err:
        messages.error(request, _("Подключение Google отменено: %(e)s") % {"e": err})
        return redirect("profile")
    code = request.GET.get("code")
    state = request.GET.get("state")
    try:
        data = signing.loads(state, salt="gcal-oauth", max_age=600)
        if data.get("uid") != request.user.pk:
            raise ValueError("uid mismatch")
    except Exception:
        messages.error(request, _("Не удалось подтвердить запрос. Попробуйте ещё раз."))
        return redirect("profile")
    try:
        tok = exchange_code(code)
    except Exception:
        messages.error(request, _("Google вернул ошибку при подключении. Попробуйте ещё раз."))
        return redirect("profile")
    refresh = tok.get("refresh_token")
    access = tok.get("access_token")
    if not access:
        messages.error(request, _("Google не выдал токен. Попробуйте ещё раз."))
        return redirect("profile")
    email = userinfo_email(access)
    acc, _created = GoogleCalendarAccount.objects.get_or_create(user=request.user)
    if refresh:
        acc.refresh_token = refresh
    acc.access_token = access
    acc.token_expiry = timezone.now() + timedelta(seconds=int(tok.get("expires_in", 3600)))
    if email:
        acc.email = email
    acc.save()
    messages.success(request, _("Google Календарь подключён%(e)s") % {
        "e": (": " + email) if email else ""})
    return redirect("profile")


@login_required
@require_POST
def google_calendar_disconnect(request):
    from apps.users.models import GoogleCalendarAccount
    GoogleCalendarAccount.objects.filter(user=request.user).delete()
    messages.success(request, _("Google Календарь отключён"))
    return redirect("profile")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("/new/" if request.user.use_new_interface else "/")
    form = LoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        # Помним, каким интерфейсом пользователь пользовался в прошлый раз
        # (User.use_new_interface — переключается заходом на /new/* или
        # ссылкой «Старый интерфейс», см. apps.users.newui_views), чтобы не
        # приходилось при каждом входе заново нажимать «Новый интерфейс».
        default_next = "/new/" if user.use_new_interface else "/"
        next_url = request.GET.get("next") or default_next
        return redirect(next_url)

    # Ссылка вида /login/?clinic=<slug> — показывает лого/название этой клиники
    # на странице входа ещё до аутентификации (до логина текущая клиника неизвестна).
    # На stom.asia то же самое определяется по поддомену (<slug>.stom.asia) —
    # см. StomAsiaRoutingMiddleware, ?clinic= там не нужен.
    from apps.tenancy import set_current_clinic, clear_current_clinic
    from apps.users.models import Clinic
    clinic_slug = (request.POST.get("clinic") or request.GET.get("clinic") or "").strip()
    clinic = Clinic.objects.filter(slug=clinic_slug, is_active=True).first() if clinic_slug else None
    if clinic is None and getattr(request, "host_clinic", None):
        clinic = request.host_clinic
        clinic_slug = clinic.slug
    try:
        if clinic:
            set_current_clinic(clinic)
        return render(request, "auth/login.html", {"form": form, "clinic_slug": clinic_slug})
    finally:
        clear_current_clinic()


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect("/login/")


@login_required
def dashboard_view(request):
    from datetime import date, timedelta
    from django.db.models import Sum, Count
    from decimal import Decimal
    user = request.user
    from apps.tenancy import get_current_clinic
    _clinic = get_current_clinic() or getattr(user, "clinic", None)
    clinic_tz = getattr(_clinic, "timezone", "") or "Asia/Bishkek"
    context = {"user": user, "clinic_tz": clinic_tz}

    # Приоритет ролей: у пользователя может быть несколько ролей одновременно
    # (например, Директор, который также записан как врач) — в этом случае
    # должен показываться дашборд более высокой (управленческой) роли, а не
    # автоматически дашборд врача.
    if user.is_superadmin or user.is_admin_main:
        import json as _json
        from datetime import datetime
        from apps.appointments.models import Appointment
        from apps.patients.models import Patient
        from apps.finance.models import Payment, Expense
        from apps.finance.views import payments_visible_to as _visible_payments_for
        from apps.treatments.models import Treatment
        today = date.today()
        year_start = today.replace(month=1, day=1)
        income_today = _visible_payments_for(Payment.objects.filter(
            created_at__date=today, type="income"
        ), user).aggregate(s=Sum("amount"))["s"] or Decimal(0)

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
            "recent_payments": _visible_payments_for(
                Payment.objects.select_related("patient").order_by("-created_at"), request.user)[:6],
            "upcoming_treatments": Treatment.objects.select_related("patient", "doctor")
                .filter(status__in=["planned", "in_progress"]).order_by("-created_at")[:6],
            "chart_months": months_ru,
            "chart_appts": appt_per_month,
            "chart_cancels": cancel_per_month,
        })
        template = "dashboard/admin.html"

    elif user.is_admin:
        from apps.appointments.models import Appointment
        from apps.tasks.models import Task
        from apps.treatments.models import Treatment
        today = date.today()
        today_appts = Appointment.objects.filter(start_at__date=today).select_related(
            "patient", "doctor", "service"
        ).order_by("start_at")

        treatments_in_progress = list(
            Treatment.objects.filter(status="in_progress")
            .select_related("patient", "doctor")
            .prefetch_related("cures__service")
            .order_by("-updated_at")[:8]
        )
        for t in treatments_in_progress:
            first_cure = t.cures.first()
            t.service_label = first_cure.service.name if first_cure else "—"
            plan = t.patient.treatment_plans.filter(status="in_progress").order_by("-created_at").first()
            total_items = plan.items.count() if plan else 0
            t.stage_label = "%s из %s" % (plan.items.filter(status="done").count(), total_items) if total_items else "—"

        context.update({
            "patients_today": today_appts.exclude(patient__isnull=True).values("patient").distinct().count(),
            "scheduled_today": today_appts.filter(status__in=["scheduled", "confirmed"]).count(),
            "completed_today": today_appts.filter(status="completed").count(),
            "cancelled_today": today_appts.filter(status="cancelled").count(),
            "today_schedule": today_appts[:8],
            "ops_tasks": Task.objects.filter(status__in=["pending", "in_progress"]).order_by("-priority", "due_date")[:5],
            "last_done_task": Task.objects.filter(
                status="done", updated_at__date__gte=today - timedelta(days=2)
            ).order_by("-updated_at").first(),
            "treatments_in_progress": treatments_in_progress,
        })
        template = "dashboard/admin_ops.html"

    elif user.is_doctor:
        from apps.appointments.models import Appointment
        from apps.patients.models import Patient
        from apps.tasks.models import Task
        today = date.today()
        my_tasks = Task.objects.filter(
            assigned_to=user, status__in=["pending", "in_progress"]
        ).order_by("-priority", "due_date")
        my_debtors = Patient.objects.filter(
            treatments__doctor=user, balance__lt=0
        ).distinct().order_by("balance")[:5]
        context.update({
            "my_appointments_today": Appointment.objects.filter(doctor=user, start_at__date=today).count(),
            "upcoming_appointments": Appointment.objects.filter(
                doctor=user, start_at__date__gte=today,
                status__in=["scheduled", "confirmed"]
            ).select_related("patient", "service").order_by("start_at")[:8],
            "my_patients_count": Patient.objects.filter(
                treatments__doctor=user
            ).distinct().count(),
            "my_tasks_count": my_tasks.count(),
            "my_tasks": my_tasks[:5],
            "my_debtors": my_debtors,
            "followups_count": 0,
            "today": today,
        })
        template = "dashboard/doctor.html"

    else:
        template = "dashboard/default.html"

    return render(request, template, context)


# ─── Staff management ────────────────────────────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def staff_list(request):
    from django.db.models import Q
    from apps.tenancy import get_current_clinic
    users = User.objects.select_related("role").prefetch_related("branches", "roles").filter(is_active=True)
    # изоляция по клинике (User не ClinicScoped — фильтруем явно)
    clinic = get_current_clinic()
    if clinic is not None:
        users = users.filter(clinic=clinic)
    # суперпользователя видит только сам суперпользователь
    if not request.user.is_superadmin:
        users = users.exclude(is_superuser=True).exclude(role__name=Role.SUPERADMIN)

    role_filter = request.GET.get("role", "all")
    if role_filter == "doctor":
        users = users.filter(Q(role__name=Role.DOCTOR) | Q(roles__name=Role.DOCTOR))
    elif role_filter == "admin":
        users = users.filter(Q(role__name__in=[Role.ADMIN, Role.ADMIN_MAIN]) | Q(roles__name__in=[Role.ADMIN, Role.ADMIN_MAIN]))
    elif role_filter == "nurse":
        users = users.filter(Q(role__name=Role.NURSE) | Q(roles__name=Role.NURSE))

    query = request.GET.get("q", "").strip()
    if query:
        users = users.filter(Q(name__icontains=query) | Q(phone__icontains=query) | Q(login__icontains=query))
    users = users.distinct()

    can_impersonate = request.user.is_superadmin or request.user.is_admin_main
    return render(request, "users/list.html", {
        "users": users, "can_impersonate": can_impersonate,
        "role_filter": role_filter, "query": query,
    })


@login_required
@require_POST
def staff_login_as(request, pk):
    """Директор/суперадмин «входит как сотрудник» (режим просмотра).

    Реальный пользователь сессии НЕ меняется — сохраняем id цели в imp_as, а оверлей
    request.user делает ImpersonationMiddleware. «Выход» мгновенный и надёжный.
    """
    # реальный пользователь (если уже в режиме просмотра — берём настоящего)
    actor = getattr(request, "impersonator", None) or request.user
    if not (actor.is_superadmin or actor.is_admin_main):
        messages.error(request, _("Доступ запрещён"))
        return redirect("staff_list")
    target = get_object_or_404(User, pk=pk)
    if target.is_superadmin and not actor.is_superadmin:
        messages.error(request, _("Нельзя войти за суперпользователя"))
        return redirect("staff_list")
    if not actor.is_superadmin and target.clinic_id != actor.clinic_id:
        messages.error(request, _("Можно войти только за сотрудника своей клиники"))
        return redirect("staff_list")
    if target.pk == actor.pk:
        return redirect("staff_list")
    request.session["imp_as"] = target.pk
    request.session.modified = True
    messages.success(request, _("Вы вошли как %(n)s. Режим просмотра.") % {"n": target.name})
    return redirect("/")


@login_required
def staff_stop_impersonate(request):
    """Выйти из режима просмотра — просто убираем оверлей (реальный пользователь не менялся)."""
    request.session.pop("imp_as", None)
    request.session.pop("impersonator_id", None)  # очистка старого ключа, если остался
    request.session.modified = True
    messages.success(request, _("Вы вернулись в свой аккаунт"))
    return redirect("/")


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
@require_permission("staff.manage")
def staff_create(request):
    from apps.tenancy import get_current_clinic
    form = UserForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        new_user = form.save(commit=False)
        # привязать к текущей клинике (или к клинике создателя)
        new_user.clinic = get_current_clinic() or getattr(request.user, "clinic", None)
        new_user.save()
        form.save_m2m()
        _apply_access_from_form(request.user, new_user, form)
        messages.success(request, _("Сотрудник добавлен"))
        return redirect("staff_list")
    return render(request, "users/form.html", {
        "form": form, "title": _("Добавить сотрудника"),
        "can_manage_access": request.user.is_superadmin or request.user.is_admin_main,
    })


@login_required
@require_permission("staff.manage")
def staff_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    # защита: суперпользователя редактирует только суперпользователь
    if _is_protected_target(user, request.user):
        messages.error(request, _("Доступ запрещён: нельзя редактировать суперпользователя"))
        return redirect("staff_list")
    form = UserForm(request.POST or None, request.FILES or None, instance=user)
    if form.is_valid():
        form.save()
        _apply_access_from_form(request.user, user, form)
        messages.success(request, _("Данные обновлены"))
        return redirect("staff_list")
    return render(request, "users/form.html", {
        "form": form, "title": _("Редактировать сотрудника"), "object": user,
        "can_manage_access": _can_manage_access(request.user, user),
    })


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def staff_purge(request, pk):
    """Удалить сотрудника навсегда. Если у него есть приёмы/записи (PROTECT) —
    удалить нельзя, оставляем деактивированным и сообщаем об этом."""
    from django.db.models import ProtectedError
    user = get_object_or_404(User, pk=pk)
    if not _can_manage_access(request.user, user):
        messages.error(request, _("Нет прав удалять этого сотрудника"))
        return redirect(request.META.get("HTTP_REFERER") or "staff_list")
    name = user.name
    try:
        user.delete()
        messages.success(request, _("Сотрудник «%(n)s» удалён") % {"n": name})
    except ProtectedError:
        if user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active"])
        messages.error(request, _("У сотрудника «%(n)s» есть приёмы/записи — удалить нельзя. "
                                  "Он деактивирован (вход заблокирован).") % {"n": name})
    return redirect(request.META.get("HTTP_REFERER")
                    or (f"/users/clinic/{user.clinic_id}/overview/" if user.clinic_id else "/users/"))


def _doctor_related_summary(user):
    """Связанные данные врача — для решения о переводе при удалении."""
    from apps.treatments.models import Treatment
    from apps.treatments.models_plan import TreatmentPlan
    from apps.appointments.models import Appointment
    from apps.patients.models import Patient
    uid = user.pk
    return {
        "patients": Patient._base_manager.filter(primary_doctor_id=uid).count(),
        "treatments": Treatment._base_manager.filter(doctor_id=uid).count(),
        "appointments": Appointment._base_manager.filter(doctor_id=uid).count(),
        "plans": TreatmentPlan._base_manager.filter(doctor_id=uid).count(),
    }


def _appt_time_conflicts(old_id, new_id):
    """Записи переводимого врача, которые пересекаются по времени с уже
    существующими записями принимающего врача (отменённые/неявки не считаем).
    Возвращает список приёмов old-врача, попавших в наложение."""
    from apps.appointments.models import Appointment
    skip = ["cancelled", "no_show"]
    old_appts = list(Appointment._base_manager.filter(doctor_id=old_id)
                     .exclude(status__in=skip).exclude(start_at__isnull=True))
    new_slots = list(Appointment._base_manager.filter(doctor_id=new_id)
                     .exclude(status__in=skip).exclude(start_at__isnull=True)
                     .values_list("start_at", "end_at"))
    conflicts = []
    for a in old_appts:
        for s, e in new_slots:
            if a.start_at and a.end_at and a.start_at < e and a.end_at > s:
                conflicts.append(a)
                break
    return conflicts


def _reassign_doctor(old_user, new_user):
    """Перевести все данные врача old_user на new_user (приёмы, записи, пациентов и т.д.).
    Возвращает список приёмов, которые после перевода пересекаются по времени с
    записями принимающего врача — чтобы предупредить администратора."""
    from django.db import transaction
    from apps.treatments.models import Treatment, TreatmentCure
    from apps.treatments.models_plan import TreatmentPlan, TreatmentPlanItem
    from apps.appointments.models import Appointment
    from apps.patients.models import Patient
    from apps.finance.models import Payment
    o, n = old_user.pk, new_user.pk
    # Конфликты считаем ДО переноса (сравниваем записи старого и нового врача).
    conflicts = _appt_time_conflicts(o, n)
    with transaction.atomic():
        Treatment._base_manager.filter(doctor_id=o).update(doctor_id=n)
        TreatmentCure._base_manager.filter(doctor_id=o).update(doctor_id=n)
        Appointment._base_manager.filter(doctor_id=o).update(doctor_id=n)
        TreatmentPlan._base_manager.filter(doctor_id=o).update(doctor_id=n)
        TreatmentPlanItem._base_manager.filter(doctor_id=o).update(doctor_id=n)
        Patient._base_manager.filter(primary_doctor_id=o).update(primary_doctor_id=n)
        Payment._base_manager.filter(received_by_id=o).update(received_by_id=n)
        # медкарты/назначения — мягко, если поля есть
        try:
            from apps.treatments.models_emr import MedicalRecord
            MedicalRecord._base_manager.filter(doctor_id=o).update(doctor_id=n)
        except Exception:
            pass
        try:
            from apps.medicines.models import PatientMedicine
            PatientMedicine._base_manager.filter(doctor_id=o).update(doctor_id=n)
        except Exception:
            pass
    return conflicts


@login_required
@role_required("superadmin", "admin_main")
def staff_delete(request, pk):
    from django.db.models import ProtectedError
    from .models import clinic_doctors
    user = get_object_or_404(User, pk=pk)
    if _is_protected_target(user, request.user):
        messages.error(request, _("Доступ запрещён: нельзя удалить суперпользователя"))
        return redirect("staff_list")
    summary = _doctor_related_summary(user)
    has_data = any(summary.values())
    # кандидаты для перевода — активные врачи той же клиники, кроме удаляемого
    candidates = (clinic_doctors(user.clinic).exclude(pk=user.pk)
                  if user.clinic_id else clinic_doctors().exclude(pk=user.pk))

    if request.method == "POST":
        if has_data:
            target_id = request.POST.get("reassign_to")
            target = candidates.filter(pk=target_id).first() if target_id else None
            if target is None:
                messages.error(request, _("Выберите врача, на которого перевести пациентов и приёмы"))
                return redirect("staff_delete", pk=pk)
            conflicts = _reassign_doctor(user, target)
            moved = f" Данные переведены на «{target.name}»."
            if conflicts:
                # Пересечения по времени — не блокируем перевод, но явно предупреждаем,
                # чтобы администратор перенёс конфликтующие записи в календаре.
                from django.utils import timezone as _tz
                examples = "; ".join(
                    f"{_tz.localtime(c.start_at):%d.%m %H:%M}" for c in conflicts[:5]
                )
                messages.warning(request, _(
                    "Внимание: %(c)d записей пересекаются по времени с расписанием врача "
                    "«%(d)s» (%(ex)s%(more)s). Откройте Расписание и перенесите их."
                ) % {"c": len(conflicts), "d": target.name, "ex": examples,
                     "more": "…" if len(conflicts) > 5 else ""})
        else:
            moved = ""
        # после перевода связей пытаемся удалить совсем, иначе деактивируем
        name = user.name
        try:
            user.delete()
            messages.success(request, _("Сотрудник «%(n)s» удалён.%(m)s") % {"n": name, "m": moved})
        except ProtectedError:
            user.is_active = False
            user.save(update_fields=["is_active"])
            messages.success(request, _("Сотрудник «%(n)s» деактивирован.%(m)s") % {"n": name, "m": moved})
        return redirect("staff_list")

    return render(request, "users/confirm_delete.html", {
        "object": user, "summary": summary, "has_data": has_data,
        "candidates": candidates,
    })


# ─── Branch management ───────────────────────────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def branch_list(request):
    branches = Branch.objects.all()
    return render(request, "users/branches.html", {"branches": branches})


@login_required
@role_required("superadmin", "admin_main")
def branch_create(request):
    if not request.user.is_superadmin and not (request.user.clinic and request.user.clinic.has_access("branches")):
        messages.error(request, _("Создание филиалов недоступно вашей клинике. Обратитесь к супер-админу."))
        return redirect("branch_list")
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
    return render(request, "users/branch_form.html", {
        "form": form, "object": branch,
        "cabinets": branch.cabinets.all(),
    })


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def cabinet_create(request, branch_pk):
    """Добавить кабинет в филиал."""
    from apps.appointments.models import Cabinet
    branch = get_object_or_404(Branch, pk=branch_pk)
    name = request.POST.get("name", "").strip()
    if name:
        Cabinet.objects.create(
            branch=branch, name=name,
            color=request.POST.get("color") or "#10B981",
        )
        messages.success(request, _("Кабинет «%(n)s» добавлен") % {"n": name})
    return redirect("branch_edit", pk=branch_pk)


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def cabinet_delete(request, pk):
    """Удалить кабинет."""
    from apps.appointments.models import Cabinet
    cab = get_object_or_404(Cabinet, pk=pk)
    branch_pk = cab.branch_id
    cab.delete()
    messages.success(request, _("Кабинет удалён"))
    return redirect("branch_edit", pk=branch_pk)


# ─── Salary ──────────────────────────────────────────────────────────────────

def _salary_rows(date_from, date_to, completed_only=False):
    """Расчёт зарплат по врачам за период [date_from, date_to]."""
    from decimal import Decimal
    from django.db.models import Sum, Count, Q
    from apps.treatments.models import Treatment
    from apps.finance.models import Payment
    from apps.users.models import clinic_staff
    from apps.tenancy import get_current_clinic
    doctors = clinic_staff(get_current_clinic())
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
        role_label = ""
        if getattr(doc, "role", None):
            role_label = doc.role.display_name
        rows.append({
            "doctor": doc, "role_label": role_label, "scheme": scheme,
            "revenue": revenue, "paid": paid,
            "treatments_count": t_count, "completed_count": c_count,
            "avg_check": avg, "salary": salary,
        })
    return rows


def _newui_salary_data():
    """Зарплаты для нового интерфейса — тот же расчёт (_salary_rows), что и
    старый /users/salary/, за текущий месяц (без выбора периода — тот же
    принцип, что и у остальных разделов нового интерфейса; полноценный
    date-range и печать остаются в старом /users/salary/, туда же ведёт
    ссылка «Excel»). Сохранение схемы — существующий POST
    /users/salary/<pk>/scheme/ (см. salary_scheme_edit), просто вызывается
    через fetch() с этой страницы, как и «Кабинеты и график» в Настройках."""
    from datetime import date
    from .models_salary import SalaryScheme

    today = date.today()
    month_start = today.replace(day=1)
    rows = _salary_rows(month_start, today)
    return {
        "periodFrom": month_start.strftime("%d.%m.%Y"),
        "periodTo": today.strftime("%d.%m.%Y"),
        "exportFrom": month_start.isoformat(),
        "exportTo": today.isoformat(),
        "schemeTypes": [{"code": c, "label": lbl} for c, lbl in SalaryScheme.TYPE_CHOICES],
        "rows": [{
            "doctorId": r["doctor"].pk,
            "doctorName": r["doctor"].name,
            "roleLabel": r["role_label"] or "—",
            "schemeType": r["scheme"].scheme_type if r["scheme"] else "",
            "schemeTypeLabel": r["scheme"].get_scheme_type_display() if r["scheme"] else "",
            "schemeFixed": float(r["scheme"].fixed_amount) if r["scheme"] else 0,
            "schemePercent": float(r["scheme"].percent) if r["scheme"] else 0,
            "schemeDescription": r["scheme"].description if r["scheme"] else "",
            "treatmentsCount": r["treatments_count"],
            "completedCount": r["completed_count"],
            "avgCheck": float(r["avg_check"]),
            "revenue": float(r["revenue"]),
            "paid": float(r["paid"]),
            "salary": float(r["salary"]),
        } for r in rows],
        "totalRevenue": float(sum(r["revenue"] for r in rows)),
        "totalPaid": float(sum(r["paid"] for r in rows)),
        "totalSalary": float(sum(r["salary"] for r in rows)),
    }


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
    ws.append(["Сотрудник", "Должность", "Схема", "Приёмов", "Завершено", "Выручка", "Оплачено", "Средний чек", "Зарплата"])
    for r in rows:
        ws.append([
            r["doctor"].name,
            r.get("role_label") or "—",
            r["scheme"].get_scheme_type_display() if r["scheme"] else "—",
            r["treatments_count"], r["completed_count"],
            float(r["revenue"]), float(r["paid"]), float(r["avg_check"]), float(r["salary"]),
        ])
    ws.append([])
    ws.append(["ИТОГО", "", "", "", "", "", "", "", float(sum(r["salary"] for r in rows))])
    for i, w in enumerate([26, 18, 20, 10, 10, 14, 14, 14, 14], start=1):
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
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic
    doctors = clinic_doctors(get_current_clinic()).prefetch_related("schedules__branch")
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


# ─── АУДИТ-ЦЕНТР (только для владельца/суперадмина) ─────────────────────────

# Поля, которые не несут смысла в диффе (служебные/технические) — не показываем.
_AUDIT_DIFF_SKIP_FIELDS = {"updated_at", "id"}


def _ru_plural(n, one, few, many):
    """Русское склонение по числу: 1 машина / 2 машины / 5 машин."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


@login_required
def audit_center(request):
    """Журнал изменений (история правок), сгруппированный по объекту, + откат
    отдельных версий. Только суперадмин."""
    if not request.user.is_superadmin:
        messages.error(request, _("Доступ только для владельца системы"))
        return redirect("/")
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    from .models import AuditRevert

    HP = Patient.history.model
    HT = Treatment.history.model
    type_label = {"+": "Создание", "~": "Изменение", "-": "Удаление"}

    def build_rows(qs, model_key, model_label, title_fn):
        out = []
        for h in qs.select_related("history_user").order_by("-history_date")[:150]:
            prev = h.prev_record
            diff = []
            if prev:
                delta = h.diff_against(prev)
                diff = [
                    {"field": c.field, "old": c.old, "new": c.new}
                    for c in delta.changes if c.field not in _AUDIT_DIFF_SKIP_FIELDS
                ]
            out.append({
                "model": model_key, "model_label": model_label, "obj_id": h.id,
                "title": title_fn(h),
                "type": type_label.get(h.history_type, h.history_type),
                "raw_type": h.history_type,
                "user": h.history_user.name if h.history_user else "—",
                "date": h.history_date, "hid": h.history_id,
                "diff": diff,
            })
        return out

    rows = build_rows(HP.objects.all(), "patient", "Пациент",
                       lambda h: f"{h.last_name} {h.first_name}".strip() or f"#{h.id}")
    rows += build_rows(HT.objects.all(), "treatment", "Приём", lambda h: f"Приём #{h.id}")
    rows.sort(key=lambda r: r["date"], reverse=True)
    recent_rows = rows[:5]

    date_filter = request.GET.get("date", "").strip()
    user_filter = request.GET.get("user", "").strip()
    action_filter = request.GET.get("action", "").strip()
    if date_filter:
        rows = [r for r in rows if r["date"].date().isoformat() == date_filter]
    if user_filter:
        rows = [r for r in rows if r["user"] == user_filter]
    if action_filter:
        rows = [r for r in rows if r["raw_type"] == action_filter]
    rows = rows[:200]

    # Записи, оказавшиеся в «устаревшей ветке» после явного отката — были
    # сделаны ПОСЛЕ версии, к которой откатили, но ДО момента самого отката.
    # Больше не описывают текущее состояние записи — показываем отдельно.
    superseded_keys = set()
    for rv in AuditRevert.objects.all():
        for r in rows:
            if (r["model"] == rv.model_label and r["obj_id"] == rv.object_id
                    and rv.reverted_to_date < r["date"] < rv.performed_at):
                superseded_keys.add((r["model"], r["hid"]))
    for r in rows:
        r["superseded"] = (r["model"], r["hid"]) in superseded_keys

    live_rows = [r for r in rows if not r["superseded"]]
    superseded_rows = [r for r in rows if r["superseded"]]

    # Группировка «текущей» истории по объекту — для аккордиона.
    groups_by_key = {}
    group_order = []
    for r in live_rows:
        key = (r["model"], r["obj_id"])
        if key not in groups_by_key:
            groups_by_key[key] = {
                "model": r["model"], "model_label": r["model_label"],
                "obj_id": r["obj_id"], "title": r["title"], "items": [],
            }
            group_order.append(key)
        groups_by_key[key]["items"].append(r)
    grouped_rows = [groups_by_key[k] for k in group_order]
    for g in grouped_rows:
        n = len(g["items"])
        g["count_label"] = f"{n} {_ru_plural(n, 'изменение', 'изменения', 'изменений')}"

    # Корзина (удалённые записи) — кратко
    deleted = []
    for Model, label in ((Patient, "Пациент"), (Treatment, "Приём")):
        try:
            for o in Model.all_objects.filter(is_deleted=True).order_by("-deleted_at")[:50]:
                deleted.append({"label": label, "title": str(o), "pk": o.pk,
                                "deleted_at": o.deleted_at,
                                "by": o.deleted_by.name if o.deleted_by else "—"})
        except Exception:
            pass
    deleted.sort(key=lambda x: x["deleted_at"] or 0, reverse=True)

    from apps.users.models import clinic_staff
    from apps.tenancy import get_current_clinic
    staff_names = clinic_staff(get_current_clinic()).values_list("name", flat=True).distinct()

    return render(request, "users/audit.html", {
        "grouped_rows": grouped_rows, "superseded_rows": superseded_rows,
        "deleted": deleted[:60], "recent_rows": recent_rows,
        "staff_names": staff_names,
        "date_filter": date_filter, "user_filter": user_filter, "action_filter": action_filter,
    })


@login_required
@require_POST
def audit_revert(request, model, hid):
    """Откатить запись к выбранной версии истории (по history_id). Записи,
    сделанные после этой версии, но до самого отката, помечаются как
    устаревшая ветка (см. audit_center) — их можно посмотреть и удалить
    отдельно, не трогая текущую (восстановленную) версию записи."""
    if not request.user.is_superadmin:
        messages.error(request, _("Доступ только для владельца системы"))
        return redirect("/")
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    from .models import AuditRevert
    Model = {"patient": Patient, "treatment": Treatment}.get(model)
    if not Model:
        return redirect("audit_center")
    h = Model.history.filter(history_id=hid).first()
    if not h:
        messages.error(request, _("Версия не найдена"))
        return redirect("audit_center")
    inst = h.instance  # объект в состоянии этой версии
    inst.save()
    AuditRevert.objects.create(
        model_label=model, object_id=inst.pk,
        reverted_to_hid=h.history_id, reverted_to_date=h.history_date,
        performed_by=request.user,
    )
    messages.success(request, _("Запись восстановлена к версии от %(d)s") % {"d": h.history_date.strftime("%d.%m.%Y %H:%M")})
    return redirect("audit_center")


@login_required
@require_POST
def audit_delete_history(request, model, hid):
    """Удалить одну устаревшую запись истории (из «ветки после отката»)."""
    if not request.user.is_superadmin:
        messages.error(request, _("Доступ только для владельца системы"))
        return redirect("/")
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    Model = {"patient": Patient, "treatment": Treatment}.get(model)
    if Model:
        Model.history.filter(history_id=hid).delete()
        messages.success(request, _("Запись истории удалена"))
    return redirect("audit_center")
