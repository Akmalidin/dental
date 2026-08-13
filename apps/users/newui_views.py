"""Разбитый на страницы новый интерфейс (был один файл templates/newui/index.html
на ~4300 строк — см. апрель/сессию с пользователем: тяжёлый единый payload на
каждый заход, невозможность дать прямую ссылку на раздел, отсутствие
постраничных прав доступа). Каждая страница — свой URL, свой view, считает
только свои данные. Общий каркас (сайдбар/CSS/JS/модалки) — templates/newui/base.html.

Данные по большинству разделов уже считались в apps.users.views._newui_*_data
(построено в предыдущих итерациях) — переиспользуем эти функции как есть,
чтобы не дублировать бизнес-логику."""
from django.contrib.auth.decorators import login_required
from django.middleware.csrf import get_token
from django.shortcuts import render

from .models import Role, Branch, Permission, clinic_doctors
from .views import (
    _newui_role_data, _newui_staff_data, _newui_dashboard_data,
    _newui_patients_data, _newui_services_data, _newui_finance_data,
    _newui_lab_data, _newui_warehouse_data, _newui_reports_data,
    _newui_schedule_data, _newui_blacklist_data, _newui_treatplans_data,
    _newui_visits_data, _newui_accounting_data, _newui_audit_data,
    _newui_patientcard_detail_data, _newui_cashdesk_data, _newui_messages_data,
    _newui_settings_data, _newui_funnel_data,
)


def _shared_options(request, clinic):
    """Опции для модалок, которые могут быть на любой странице (форма
    сотрудника/пациента/услуги и т.п. — общий base.html их всегда рендерит)."""
    from apps.patients.models import LeadSource
    from apps.settings_clinic.models import ClinicSettings
    return {
        # Язык интерфейса — реальная настройка клиники (Настройки → Общие),
        # уже сохраняется через ClinicSettingsForm/language. Нужен на КАЖДОЙ
        # странице (не только settings.html), чтобы подписи меню в base.html
        # переводились сразу при заходе, а не только пока открыта сама
        # страница настроек.
        "clinicLanguage": ClinicSettings.get().language or "ru",
        "roleOptions": [
            {"id": r.pk, "name": r.display_name}
            for r in Role.objects.filter(clinic__isnull=True).exclude(name=Role.SUPERADMIN).order_by("name")
        ],
        "branchOptions": [{"id": b.pk, "name": b.name} for b in Branch.objects.all().order_by("name")],
        "permCatalog": [
            {"code": p.code, "label": p.label, "category": p.category, "categoryLabel": p.get_category_display()}
            for p in Permission.objects.all().order_by("category", "sort_order", "label")
        ],
        "doctorOptions": [{"id": u.pk, "name": u.name} for u in clinic_doctors(clinic).order_by("name")],
        "sourceOptions": [{"id": s.pk, "name": s.name} for s in LeadSource.objects.all().order_by("name")],
    }


def _render(request, page, template, extra_data=None):
    from apps.tenancy import get_current_clinic
    get_token(request)  # cookie csrftoken для fetch()-запросов из модалок
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    real_data = _shared_options(request, clinic)
    real_data.update(extra_data or {})
    return render(request, f"newui/{template}", {
        "active": page,
        "active_clinic": clinic,
        "real_data": real_data,
    })


@login_required
def newui_dashboard(request):
    # Кнопка "+ Новая запись" на дашборде открывает ту же модалку, что и
    # /new/schedule/ — ей тоже нужны реальные пациенты/услуги.
    return _render(request, "dashboard", "dashboard.html", {
        "dashboard": _newui_dashboard_data(),
        "servicesData": _newui_services_data(),
        "patients": _newui_patients_data(),
    })


@login_required
def newui_staff(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "staff", "staff.html", {
        "roles": _newui_role_data(clinic),
        "staff": _newui_staff_data(request, clinic),
    })


@login_required
def newui_patients(request):
    return _render(request, "patients", "patients.html", {"patients": _newui_patients_data()})


@login_required
def newui_patientcard(request, pk):
    """Карта одного пациента. JS-логика (openPatientCard) написана под поиск
    по массиву patientsList — отдаём список из одного элемента и открываем
    его автоматически при загрузке, не переписывая рабочий фронтенд-код."""
    from apps.patients.models import Patient
    all_patients = _newui_patients_data()
    patient = next((p for p in all_patients if p["id"] == pk), None)
    extra = {"patients": [patient] if patient else [], "openPatientId": pk if patient else None}
    if patient:
        patient_obj = Patient.all_objects.filter(pk=pk).first()
        if patient_obj:
            extra["patientCardDetail"] = _newui_patientcard_detail_data(patient_obj)
    return _render(request, "patientcard", "patientcard.html", extra)


@login_required
def newui_schedule(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "schedule", "schedule.html", {
        "schedule": _newui_schedule_data(clinic),
        # Модалка "Новая запись" на этой странице ищет пациента и услугу так
        # же, как на /new/patients/ и /new/services/ — переиспользуем те же
        # хелперы, без дублирования бизнес-логики.
        "servicesData": _newui_services_data(),
        "patients": _newui_patients_data(),
    })


@login_required
def newui_services(request):
    return _render(request, "services", "services.html", {"servicesData": _newui_services_data()})


@login_required
def newui_finance(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "finance", "finance.html", {"financeData": _newui_finance_data(clinic)})


@login_required
def newui_lab(request):
    return _render(request, "lab", "lab.html", {"labData": _newui_lab_data()})


@login_required
def newui_warehouse(request):
    return _render(request, "warehouse", "warehouse.html", {"warehouseData": _newui_warehouse_data()})


@login_required
def newui_reports(request):
    return _render(request, "reports", "reports.html", {"reportsData": _newui_reports_data()})


# ── Разделы без реального бэкенда (см. баннеры в самих шаблонах) — просто
#    статические страницы, чтобы у каждого раздела меню была своя страница.
@login_required
def newui_funnel(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "funnel", "funnel.html", {"funnelData": _newui_funnel_data(clinic)})


@login_required
def newui_blacklist(request):
    return _render(request, "blacklist", "blacklist.html", {"blacklistEntries": _newui_blacklist_data()})


@login_required
def newui_visit_start(request):
    """«Начать/продолжить приём» из нового интерфейса — та же логика поиска/
    создания Treatment, что и старый /treatments/visit/start/ (см.
    apps.treatments.views_visit._resolve_or_create_visit), просто ведёт на
    /new/visitcard/<id>/ вместо старого /treatments/visit/<id>/."""
    from django.contrib import messages
    from django.shortcuts import redirect
    from apps.treatments.views_visit import _resolve_or_create_visit

    status, payload = _resolve_or_create_visit(request)
    if status == "no_patient":
        messages.error(request, "Не указан пациент для приёма")
        return redirect("newui_schedule")
    if status == "completed":
        return redirect("newui_visitcard", pk=payload.pk)
    if status == "appt_done":
        messages.info(request, "Запись уже завершена. Новый приём не создаётся.")
        return redirect("newui_patientcard", pk=payload.pk)
    return redirect("newui_visitcard", pk=payload.pk)


@login_required
def newui_visitcard(request, pk):
    """Карточка приёма — тот же мастер (ЭМК/зубы/процедуры/файлы), что и
    старый /treatments/visit/<pk>/ (apps.treatments.views_visit.visit_wizard),
    те же данные (_visit_wizard_context), просто в дизайне нового интерфейса."""
    from django.shortcuts import get_object_or_404, redirect
    from apps.treatments.models import Treatment
    from apps.treatments.views_visit import _visit_wizard_context
    from apps.notifications.whatsapp import wa_enabled
    from apps.notifications.telegram import tg_enabled

    treatment = get_object_or_404(
        Treatment.objects.select_related("patient", "doctor", "branch", "appointment")
        .prefetch_related("cures__service"),
        pk=pk,
    )
    _emr, ctx = _visit_wizard_context(treatment)
    ctx["waEnabled"] = wa_enabled()
    ctx["tgEnabled"] = tg_enabled()
    return _render(request, "visitcard", "visitcard.html", {"visitWizard": ctx})


@login_required
def newui_audit(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "audit", "audit.html", {"auditEvents": _newui_audit_data(clinic)})


@login_required
def newui_visits(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    # "+ Новый визит" открывает ту же модалку "Новая запись", что и
    # /new/schedule/ — ей нужны реальные пациенты/услуги.
    return _render(request, "visits", "visits.html", {
        "visitsData": _newui_visits_data(clinic),
        "servicesData": _newui_services_data(),
        "patients": _newui_patients_data(),
    })


@login_required
def newui_treatplans(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "treatplans", "treatplans.html", {"treatplansData": _newui_treatplans_data(clinic)})


@login_required
def newui_cashdesk(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "cashdesk", "cashdesk.html", {"cashdeskData": _newui_cashdesk_data(request, clinic)})


@login_required
def newui_accounting(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "accounting", "accounting.html", {"accountingData": _newui_accounting_data(clinic)})


@login_required
def newui_messages(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "messages", "messages.html", {"messagesData": _newui_messages_data(clinic)})


@login_required
def newui_marketing(request):
    return _render(request, "marketing", "marketing.html")


@login_required
def newui_settings(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "settings", "settings.html", {"settingsData": _newui_settings_data(clinic)})
