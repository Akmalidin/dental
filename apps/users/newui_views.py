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

from .decorators import role_required
from .models import Role, Branch, Permission, SECTIONS, clinic_doctors
from .views import (
    _newui_role_data, _newui_staff_data, _newui_dashboard_data,
    _newui_patients_data, _newui_patients_page_data, _newui_patient_by_pk, _newui_services_data, _newui_finance_data,
    _newui_lab_data, _newui_warehouse_data, _newui_reports_data,
    _newui_schedule_data, _newui_blacklist_data, _newui_treatplans_data,
    _newui_visits_data, _newui_accounting_data, _newui_audit_data,
    _newui_patientcard_detail_data, _newui_cashdesk_data, _newui_messages_data,
    _newui_settings_data, _newui_funnel_data, _newui_salary_data, _newui_profile_data,
)


def _shared_options(request, clinic):
    """Опции для модалок, которые могут быть на любой странице (форма
    сотрудника/пациента/услуги и т.п. — общий base.html их всегда рендерит)."""
    from apps.patients.models import LeadSource
    from apps.settings_clinic.models import ClinicSettings
    from apps.notifications.voice import voice_enabled, ai_enabled
    cs = ClinicSettings.get()
    return {
        # Язык интерфейса — реальная настройка клиники (Настройки → Общие),
        # уже сохраняется через ClinicSettingsForm/language. Нужен на КАЖДОЙ
        # странице (не только settings.html), чтобы подписи меню в base.html
        # переводились сразу при заходе, а не только пока открыта сама
        # страница настроек.
        "clinicLanguage": cs.language or "ru",
        # Валюта клиники — нужна на КАЖДОЙ странице (не только settings.html),
        # т.к. fmtSom()/формат сумм в base.html общий для всего интерфейса.
        "clinicCurrencySymbol": cs.currency_label,
        "clinicCurrencySecondarySymbol": cs.currency_secondary_label,
        "clinicHasSecondaryCurrency": cs.has_secondary_currency,
        # Настройка меню (сайдбара) — личная (per-user, между устройствами) и
        # клиникина по умолчанию (директор задаёт в Настройках → «Меню клиники»,
        # применяется всем, у кого нет своей личной). base.html сам решает
        # приоритет в loadMenuPrefs(). canSetClinicMenu — показывать ли саму
        # вкладку «Меню клиники» в Настройках (только директор/суперадмин).
        "userMenuPrefs": getattr(request.user, "menu_prefs", None) or {},
        "clinicMenuPrefs": cs.menu_prefs or {},
        "canSetClinicMenu": bool(request.user.is_superadmin or request.user.has_role("admin_main")),
        "roleOptions": [
            # roleKey — стабильный системный ключ роли (Role.DOCTOR и т.п., не
            # зависит от языка/переименования display_name) — нужен, чтобы
            # подсказывать разумный набор разделов при первом снятии «Полного
            # доступа» в карточке сотрудника (см. ROLE_SECTION_DEFAULTS в base.html).
            {"id": r.pk, "name": r.display_name, "roleKey": r.name}
            for r in Role.objects.filter(clinic__isnull=True).exclude(name=Role.SUPERADMIN).order_by("name")
        ],
        "branchOptions": [{"id": b.pk, "name": b.name} for b in Branch.objects.all().order_by("name")],
        "permCatalog": [
            {"code": p.code, "label": p.label, "category": p.category, "categoryLabel": p.get_category_display()}
            for p in Permission.objects.all().order_by("category", "sort_order", "label")
        ],
        "doctorOptions": [{"id": u.pk, "name": u.name} for u in clinic_doctors(clinic).order_by("name")],
        "sourceOptions": [{"id": s.pk, "name": s.name} for s in LeadSource.objects.all().order_by("name")],
        # Расписание: подсказка «начать приём» после отметки «Пришёл» должна
        # предлагаться только врачу, не администратору/ресепшену.
        "isDoctor": bool(request.user.is_doctor),
        # Касса → «Быстрая продажа»: прячем кнопку у тех, у кого нет права
        # (иначе клик просто упёрся бы в 403 без объяснения).
        "canQuickSale": bool(request.user.is_superadmin or
                             (request.user.role_id and request.user.role.has_perm("finance.quick_sale"))),
        # Карта пациента → «История приёмов»: кнопка удаления записи — прячем
        # у тех, у кого нет права (иначе клик просто упёрся бы в 403).
        "canDeleteHistory": bool(request.user.is_superadmin or
                                 (request.user.role_id and request.user.role.has_perm("patients.delete_history"))),
        # Голосовой ввод (диктовка в карту + голосовые команды по расписанию) —
        # плавающий виджет на всех страницах, скрыт целиком, если ключ OpenAI
        # не настроен на сервере (тот же безопасно-выключенный паттерн, что
        # и у GreenAPI).
        "voiceEnabled": voice_enabled(),
        # Свободный вопрос-ответ (YandexGPT) — включает и голосовой fallback
        # («спроси что угодно» в плавающем виджете), и реальный ответ в
        # текстовом чате «ИИ-помощник» на странице Отчётов.
        "aiEnabled": ai_enabled(),
        # «Ограничение доступа» в карточке сотрудника (Персонал → редактирование) —
        # тот же персональный механизм allowed_sections, что и в старом интерфейсе
        # (см. apps.users.forms.UserForm.sections/full_access, apps.users.views.
        # _apply_access_from_form). sectionsCatalog — список разделов для чекбоксов,
        # currentUserId — чтобы скрыть блок при редактировании самого себя (нельзя
        # ограничить самому себе доступ и остаться без возможности его вернуть).
        "sectionsCatalog": [{"key": k, "label": lbl} for k, lbl, _url in SECTIONS if k != "dashboard"],
        "currentUserId": request.user.pk,
        # Пункты сайдбара, к которым у пользователя ЛИЧНО есть доступ (allowed_
        # sections) — сайдбар прячет остальные (см. hideRestrictedNavItems в
        # base.html), чтобы не показывать ссылку, по которой всё равно
        # редиректнёт SectionAccessMiddleware (apps/tenancy.py). Раньше сайдбар
        # это никак не учитывал — все пункты были видны независимо от
        # ограничения, кликабельны, но вели в никуда.
        "navSections": sorted(request.user.nav_sections),
    }


def _render(request, page, template, extra_data=None):
    from apps.tenancy import get_current_clinic
    get_token(request)  # cookie csrftoken для fetch()-запросов из модалок
    # Запоминаем «пользователь сейчас на новом интерфейсе» — чтобы при следующем
    # входе login_view сразу вёл в /new/, а не на старый дашборд (см.
    # User.use_new_interface). update() вместо save() — не гонять историю/сигналы
    # ради одного поля на каждой странице, и пишем только если значение меняется.
    if not request.user.use_new_interface:
        from .models import User
        # request.user — SimpleLazyObject (type() вернул бы сам враппер, не модель),
        # поэтому используем импортированный User напрямую.
        User.objects.filter(pk=request.user.pk).update(use_new_interface=True)
        request.user.use_new_interface = True
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
def newui_patients_data_json(request):
    """AJAX: страница списка пациентов с реальной серверной пагинацией/
    поиском/фильтром (в клинике может быть тысячи пациентов — компактный
    встроенный patientsList (см. _newui_patients_data, лимит 300) годится
    только для быстрого поиска в модалках на других страницах, не для самого
    списка). Дергается из renderPatientsTable() в base.html."""
    from django.http import JsonResponse
    return JsonResponse(_newui_patients_page_data(request))


@login_required
def newui_patientcard(request, pk):
    """Карта одного пациента. JS-логика (openPatientCard) написана под поиск
    по массиву patientsList — отдаём список из одного элемента и открываем
    его автоматически при загрузке, не переписывая рабочий фронтенд-код.
    _newui_patient_by_pk ищет пациента напрямую по pk (не через капнутый на
    300 _newui_patients_data) — иначе карточка «старого» пациента (не из
    последних 300 созданных) не открывалась бы вовсе."""
    from apps.patients.models import Patient
    patient = _newui_patient_by_pk(pk)
    extra = {"patients": [patient] if patient else [], "openPatientId": pk if patient else None}
    if patient:
        patient_obj = Patient.objects.filter(pk=pk).first()
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
def newui_schedule_data_json(request):
    """AJAX: те же данные расписания, что и на /new/schedule/ (_newui_schedule_data) —
    для страниц, которым эти данные нужны лишь ситуативно (напр. кнопка
    «Новая запись» на карточке пациента подбирает реально свободное время у
    врача — см. openNewApptForCurrentPatient/findNextFreeSlot в base.html).
    Грузить полное расписание на каждый заход на такие страницы (карту
    пациента открывают на порядок чаще календаря) было бы расточительно —
    подгружаем по требованию и кэшируем на клиенте на время сессии страницы."""
    from django.http import JsonResponse
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return JsonResponse(_newui_schedule_data(clinic))


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


@login_required
@role_required("superadmin", "admin_main")
def newui_salary(request):
    """Зарплаты и схемы — те же права, что и старый /users/salary/
    (только директор/суперадмин, см. apps.users.views.salary_report)."""
    return _render(request, "salary", "salary.html", {"salaryData": _newui_salary_data()})


@login_required
def newui_profile(request):
    """Профиль — доступен всем (не только директору/суперадмину, в отличие
    от Зарплат): свой аватар/пароль/WhatsApp/Google Calendar меняет любой
    сотрудник."""
    return _render(request, "profile", "profile.html", {"profileData": _newui_profile_data(request.user)})


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
    return _render(request, "cashdesk", "cashdesk.html", {
        "cashdeskData": _newui_cashdesk_data(request, clinic),
        # «Быстрая продажа» нужны врачи/услуги/пациенты — эта страница их
        # раньше не запрашивала (в отличие от visits/schedule/dashboard).
        "servicesData": _newui_services_data(),
        "patients": _newui_patients_data(),
    })


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


@login_required
def newui_menu_prefs_save(request):
    """Сохранение настройки сайдбара («Настроить меню» / «Меню клиники» в
    Настройках) — POST JSON {"prefs": {...}, "scope": "user"|"clinic"}.
    scope="user" — личная настройка (User.menu_prefs), доступна всем.
    scope="clinic" — меню по умолчанию для ВСЕХ сотрудников (ClinicSettings.menu_prefs),
    только для директора/суперадмина — обычный сотрудник не должен иметь возможность
    незаметно поменять сайдбар всем коллегам."""
    from django.http import JsonResponse
    import json

    if request.method != "POST":
        return JsonResponse({"error": "POST only", "error_key": "generic_post_only"}, status=405)
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid JSON", "error_key": "generic_invalid_json"}, status=400)
    prefs = data.get("prefs")
    if not isinstance(prefs, dict):
        return JsonResponse({"error": "prefs required", "error_key": "menu_prefs_required"}, status=400)
    scope = data.get("scope", "user")
    prefs = {
        "hidden": prefs.get("hidden") or [],
        "order": prefs.get("order") or {},
        "home": prefs.get("home"),
    }
    if scope == "clinic":
        if not (request.user.is_superadmin or request.user.has_role("admin_main")):
            return JsonResponse({"error": "Только директор может менять меню клиники", "error_key": "menu_only_director"}, status=403)
        from apps.settings_clinic.models import ClinicSettings
        cs = ClinicSettings.get()
        cs.menu_prefs = prefs
        cs.save(update_fields=["menu_prefs"])
    else:
        request.user.menu_prefs = prefs
        request.user.save(update_fields=["menu_prefs"])
    return JsonResponse({"ok": True})


@login_required
def newui_use_old_interface(request):
    """Ссылка «Старый интерфейс» в сайдбаре — явный выбор пользователя вернуться
    к старому UI, поэтому здесь (в отличие от _render выше) снимаем флажок
    use_new_interface, чтобы следующий вход снова вёл на старый дашборд."""
    if request.user.use_new_interface:
        from .models import User
        User.objects.filter(pk=request.user.pk).update(use_new_interface=False)
    from django.shortcuts import redirect
    return redirect("/")
