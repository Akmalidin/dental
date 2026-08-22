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
    _newui_visits_data, _newui_accounting_data, _newui_audit_data, _newui_notifications_data,
    _newui_patientcard_detail_data, _newui_cashdesk_data, _newui_messages_data,
    _newui_settings_data, _newui_funnel_data, _newui_salary_data, _newui_profile_data,
    _newui_tasks_data, _newui_medicines_data, _newui_recycle_data,
    _newui_technicians_data, _newui_warehouse_ops_data,
    _newui_visits_journal_data, _newui_superadmin_data,
)


def _message_templates_queryset():
    """Реальные шаблоны сообщений (apps.notifications.models.MessageTemplate),
    с тем же ленивым сидированием набора по умолчанию, что и у старого
    интерфейса (apps.notifications.views.message_templates) — если у клиники
    ещё нет ни одного шаблона, создаём стандартный набор при первом заходе."""
    from apps.notifications.models import MessageTemplate
    from apps.notifications.whatsapp import seed_default_templates
    if not MessageTemplate.objects.exists():
        try:
            seed_default_templates()
        except Exception:
            pass
    return MessageTemplate.objects.all()


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
        # Шаблоны сообщений (Мессенджеры → «Шаблоны», карта приёма → выбор
        # шаблона) — реальные MessageTemplate из БД, общие со старым
        # интерфейсом (apps.notifications.views.message_templates). Раньше
        # addTemplate/deleteTemplate в новом интерфейсе мутировали только
        # JS-массив, ничего не сохраняя на сервере — шаблоны терялись при
        # перезагрузке страницы (баг с прода). Название полей (title/text,
        # не name/body) — под уже существующий JS-код нового интерфейса,
        # который их так и использует.
        "messageTemplates": [
            {"id": t.pk, "title": t.name, "text": t.body}
            for t in _message_templates_queryset()
        ],
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
        # Список/карта пациента → «Удалить» (в корзину, не безвозвратно — та
        # же вьюха, что и в старом интерфейсе, apps.patients.views.
        # patient_delete). Прячем у тех, у кого нет права patients.delete.
        "canDeletePatient": bool(request.user.is_superadmin or
                                 (request.user.role_id and request.user.role.has_perm("patients.delete"))),
        # Журнал аудита → кнопка «Откатить» — необратимо перезаписывает
        # текущее состояние объекта прошлым значением из истории, поэтому
        # только суперадминистратору (см. apps.users.newui_views.audit_revert).
        "isSuperadmin": bool(request.user.is_superadmin),
        # Задачи → кнопка «Удалить» — та же проверка прав, что и в старом
        # интерфейсе (apps.tasks.views.task_delete: автор, админ или
        # суперадмин), прячем у остальных, чтобы не упираться в отказ.
        "isAdmin": bool(request.user.is_admin),
        # Корзина → «Удалить навсегда» — строже, чем просто is_admin
        # (та же граница прав, что у apps.users.views.recycle_purge:
        # superadmin/admin_main, НЕ обычный admin).
        "isAdminMain": bool(request.user.is_admin_main),
        # Журнал посещений — виден в сайдбаре по умолчанию всем (та же
        # настройка, что и в старом интерфейсе, clinic_settings.visits_journal_staff),
        # директор может скрыть его от рядового персонала кнопкой на самой
        # странице (admin/admin_main/superadmin видят его всегда — см.
        # apps.patients.views._visits_journal_allowed).
        "visitsJournalStaff": bool(cs.visits_journal_staff),
        # Корзина — в отличие от журнала посещений, изначально скрыта ото
        # всех (та же настройка, что и в старом интерфейсе,
        # clinic_settings.recycle_bin_staff, по умолчанию False), директор
        # включает явно. superadmin — всегда (см. apps.users.views.
        # _recycle_bin_allowed).
        "recycleBinStaff": bool(cs.recycle_bin_staff),
        # Голосовой ввод (диктовка в карту + голосовые команды по расписанию) —
        # плавающий виджет на всех страницах, скрыт целиком, если ключ OpenAI
        # не настроен на сервере (тот же безопасно-выключенный паттерн, что
        # и у GreenAPI), И если супер-админ явно заблокировал его этой
        # клинике (Clinic.blocked_features, "voice_bot" — см. /new/superadmin/).
        "voiceEnabled": voice_enabled() and not (clinic and clinic.is_blocked("voice_bot")),
        # Свободный вопрос-ответ (YandexGPT) — включает и голосовой fallback
        # («спроси что угодно» в плавающем виджете), и реальный ответ в
        # текстовом чате «ИИ-помощник» на странице Отчётов.
        "aiEnabled": ai_enabled() and not (clinic and clinic.is_blocked("voice_bot")),
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
    списка). Дергается из renderPatientsTable() в base.html. Учитывает
    активный филиал переключателя сайдбара (request.session["active_branch"])
    — см. _newui_patients_page_data."""
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
    from apps.tenancy import get_current_clinic, get_active_branch_id
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "schedule", "schedule.html", {
        "schedule": _newui_schedule_data(clinic, get_active_branch_id(request)),
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
    from apps.tenancy import get_current_clinic, get_active_branch_id
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return JsonResponse(_newui_schedule_data(clinic, get_active_branch_id(request)))


@login_required
def newui_services(request):
    # Лёгкий список материалов склада (id/название/ед.) — только для
    # выпадающего списка в «Нормативы расхода» (материал → услуга, авто-
    # списание), полный _newui_warehouse_ops_data() тяжелее и нужен только
    # странице «Склад» (тот же паттерн, что и warehouseProducts у staff).
    from apps.warehouse.models import Product
    warehouse_products = [{"id": p.pk, "name": p.name, "unit": p.unit}
                           for p in Product.objects.filter(is_active=True).order_by("name")]
    return _render(request, "services", "services.html", {
        "servicesData": _newui_services_data(),
        "warehouseProductsLite": warehouse_products,
    })


@login_required
def newui_finance(request):
    from apps.tenancy import get_current_clinic, get_active_branch_id
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "finance", "finance.html", {
        "financeData": _newui_finance_data(clinic, get_active_branch_id(request)),
    })


@login_required
def newui_lab(request):
    return _render(request, "lab", "lab.html", {
        "labData": _newui_lab_data(),
        "techniciansData": _newui_technicians_data(),
    })


@login_required
def newui_warehouse(request):
    from apps.tenancy import get_active_branch_id
    return _render(request, "warehouse", "warehouse.html", {
        # Остатки (_newui_warehouse_data) НЕ фильтруются по филиалу — учёт
        # материалов в системе ведётся клиникой в целом (Product.quantity —
        # один общий остаток, без разбивки по филиалам), фильтруется по
        # филиалу только сама история операций.
        "warehouseData": _newui_warehouse_data(),
        "warehouseOpsData": _newui_warehouse_ops_data(get_active_branch_id(request)),
    })


@login_required
def newui_reports(request):
    from apps.tenancy import get_active_branch_id
    return _render(request, "reports", "reports.html", {
        "reportsData": _newui_reports_data(get_active_branch_id(request)),
    })


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
def newui_visits_journal(request):
    """Журнал посещений — видимость страницы для не-админов проверяется
    здесь же (та же граница, что у apps.patients.views._visits_journal_allowed);
    SectionAccessMiddleware (apps/tenancy.py, секция "patients") — это доступ
    к разделу вообще, а видимость самого журнала персоналу — отдельная
    настройка клиники (ClinicSettings.visits_journal_staff), директор
    включает/выключает её тут же, кнопкой на странице."""
    from django.contrib import messages
    from django.shortcuts import redirect
    from apps.tenancy import get_current_clinic
    from apps.patients.views import _visits_journal_allowed
    if not _visits_journal_allowed(request.user):
        messages.error(request, "Журнал посещений скрыт администратором")
        return redirect("/new/")
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "visitsjournal", "visits_journal.html", {
        "visitsJournalData": _newui_visits_journal_data(request, clinic),
        "patients": _newui_patients_data(),
        "servicesData": _newui_services_data(),
    })


@login_required
def newui_tasks(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "tasks", "tasks.html", {"tasksData": _newui_tasks_data(request, clinic)})


@login_required
def newui_medicines(request):
    return _render(request, "medicines", "medicines.html", {
        "medicinesData": _newui_medicines_data(request),
        # Поиск пациента в модалке «Назначить лекарство» (rxPatientSearch,
        # base.html) — использует общий patientsList, но он не входит в
        # _shared_options (страница пациентов сама решает, кому он нужен —
        # см. cashdesk/messages, тот же паттерн).
        "patients": _newui_patients_data(),
    })


@login_required
@role_required("superadmin", "admin_main", "admin")
def newui_recycle(request):
    """Корзина — те же права, что и старый /users/recycle-bin/
    (apps.users.views.recycle_bin: superadmin/admin_main/admin), плюс та же
    граница видимости — изначально скрыта ото всех, включается настройкой
    клиники (apps.users.views._recycle_bin_allowed)."""
    from django.contrib import messages
    from django.shortcuts import redirect
    from apps.users.views import _recycle_bin_allowed
    if not _recycle_bin_allowed(request.user):
        messages.error(request, "Корзина скрыта администратором")
        return redirect("/new/")
    return _render(request, "recycle", "recycle.html", {"recycleData": _newui_recycle_data(request)})


@login_required
def newui_superadmin(request):
    """Супер-админ-панель нового интерфейса — «2 в 1» (Аудит-центр):
    вкладка «Лента событий» (платформенный журнал безопасности) + вкладки
    «Клиники»/«Пользователи»/«Блокировки IP» на одной странице. Раньше это
    был только список клиник — тот функционал никуда не делся (вкладка
    «Клиники», тот же _newui_superadmin_data, те же вьюхи-мутации старого
    интерфейса), просто больше не единственный экран страницы.

    Сама лента/метрики/список пользователей — не встроены в начальный
    payload (могут быть большими и требуют фильтрации/пагинации), а
    грузятся по AJAX при открытии вкладки — см. newui_superadmin_feed/
    newui_superadmin_users, тот же приём, что и у newui_patients_data_json/
    newui_schedule_data_json для «тяжёлых» списков."""
    from django.contrib import messages
    from django.shortcuts import redirect
    if not request.user.is_superadmin:
        messages.error(request, "Доступ только для суперадмина")
        return redirect("/new/")
    from .audit import superadmin_audit_metrics
    return _render(request, "superadmin", "superadmin.html", {
        "superadminData": _newui_superadmin_data(),
        "auditMetrics": superadmin_audit_metrics(),
    })


@login_required
def newui_superadmin_feed(request):
    """AJAX: страница «Ленты событий» (фильтр по категории/датам/поиску,
    пагинация) — см. apps.users.audit.superadmin_audit_feed. Дёргается при
    открытии вкладки и при смене фильтров/странице списка."""
    from django.http import JsonResponse
    from datetime import datetime
    if not request.user.is_superadmin:
        return JsonResponse({"error": "Доступно только суперадмину"}, status=403)
    from .audit import superadmin_audit_feed, superadmin_audit_metrics

    def _parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    category = request.GET.get("category", "all")
    date_from = _parse_date(request.GET.get("date_from", ""))
    date_to = _parse_date(request.GET.get("date_to", ""))
    search = request.GET.get("search", "")
    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        page = 1
    feed = superadmin_audit_feed(category=category, date_from=date_from, date_to=date_to,
                                  search=search, page=page)
    for r in feed["rows"]:
        r["created_at"] = r["created_at"].strftime("%d.%m.%Y %H:%M:%S")
    return JsonResponse({**feed, "metrics": superadmin_audit_metrics()})


@login_required
def newui_superadmin_event_detail(request, event_id):
    """AJAX: «Запись аудита» — детальная карточка одного события. IP →
    геолокация и User-Agent → устройство считаются ТОЛЬКО здесь, по
    открытию карточки (см. apps.users.geoip/ua_parse), не на каждой строке
    ленты — сетевой вызов к ip-api.com не должен тормозить список.

    event_id — составной: "evt:<pk>" (AuditEvent), "login:<pk>"
    (ClinicLoginEvent) или "hist:<model>:<hid>" (simple_history Patient/
    Treatment) — см. apps.users.audit._event_row/_login_row/_history_row,
    строящие те же id для строк ленты."""
    from django.http import JsonResponse
    if not request.user.is_superadmin:
        return JsonResponse({"error": "Доступно только суперадмину"}, status=403)
    from .models import AuditEvent, ClinicLoginEvent
    from .geoip import get_ip_geolocation
    from .ua_parse import parse_user_agent
    from .audit import ACTION_LABELS, _AUDIT_DIFF_SKIP_FIELDS

    parts = event_id.split(":")
    kind = parts[0] if parts else ""
    data = None

    if kind == "evt" and len(parts) == 2:
        e = AuditEvent.objects.filter(pk=parts[1]).select_related("actor", "clinic").first()
        if e:
            data = {
                "action_label": ACTION_LABELS.get(e.action, e.action),
                "created_at": e.created_at.strftime("%d.%m.%Y %H:%M:%S"),
                "actor_label": e.actor_name or "—",
                "actor_role": e.actor_role or "",
                "object_repr": e.object_repr or "—",
                "ip": e.ip_address or "—",
                "geo": get_ip_geolocation(e.ip_address) if e.ip_address else None,
                "device": parse_user_agent(e.user_agent) if e.user_agent else "—",
                "result": "Успех" if e.result == "success" else "Отказ",
                "diff": e.diff or [],
                "open_user_url": (f"/users/{e.object_id}/edit/"
                                  if e.object_model == "user" and e.object_id else None),
            }
    elif kind == "login" and len(parts) == 2:
        ev = ClinicLoginEvent.objects.filter(pk=parts[1]).select_related("user", "clinic").first()
        if ev:
            data = {
                "action_label": "Вход в систему" if ev.success else "Отказ во входе",
                "created_at": ev.created_at.strftime("%d.%m.%Y %H:%M:%S"),
                "actor_label": ev.user.name if ev.user else "—",
                "actor_role": (ev.user.role_name or "") if ev.user else "",
                "object_repr": f"user/{ev.user_id}" if ev.user_id else "—",
                "ip": ev.ip_address or "—",
                "geo": get_ip_geolocation(ev.ip_address) if ev.ip_address else None,
                "device": parse_user_agent(ev.user_agent) if ev.user_agent else "—",
                "result": "Успех" if ev.success else "Отказ",
                "diff": [],
                "open_user_url": f"/users/{ev.user_id}/edit/" if ev.user_id else None,
            }
    elif kind == "hist" and len(parts) == 3:
        from apps.patients.models import Patient
        from apps.treatments.models import Treatment
        model_key, hid = parts[1], parts[2]
        Model = {"patient": Patient, "treatment": Treatment}.get(model_key)
        h = Model.history.filter(history_id=hid).select_related("history_user").first() if Model else None
        if h:
            type_label = {"+": "Создание", "~": "Изменение", "-": "Удаление"}
            prev = h.prev_record
            diff = []
            if prev:
                delta = h.diff_against(prev)
                diff = [{"field": c.field, "old": str(c.old), "new": str(c.new)}
                        for c in delta.changes if c.field not in _AUDIT_DIFF_SKIP_FIELDS]
            model_label = "Пациент" if model_key == "patient" else "Приём"
            data = {
                "action_label": f"{type_label.get(h.history_type, h.history_type)}: {model_label}",
                "created_at": h.history_date.strftime("%d.%m.%Y %H:%M:%S"),
                "actor_label": h.history_user.name if h.history_user else "—",
                "actor_role": (h.history_user.role_name or "") if h.history_user else "",
                "object_repr": f"{model_key}/{h.id}",
                "ip": "—", "geo": None, "device": "—",
                "result": "Успех",
                "diff": diff,
                "open_user_url": None,
            }

    if data is None:
        return JsonResponse({"error": "Событие не найдено"}, status=404)
    return JsonResponse(data)


@login_required
def newui_superadmin_audit_export(request):
    """CSV-экспорт отфильтрованной ленты (те же параметры фильтра, что и у
    AJAX-страницы) — без пагинации, стандартный csv.writer + StreamingHttpResponse
    (без новых зависимостей)."""
    import csv
    from datetime import datetime
    from django.http import HttpResponseForbidden, StreamingHttpResponse
    if not request.user.is_superadmin:
        return HttpResponseForbidden("Доступно только суперадмину")
    from .audit import superadmin_audit_feed

    def _parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    category = request.GET.get("category", "all")
    date_from = _parse_date(request.GET.get("date_from", ""))
    date_to = _parse_date(request.GET.get("date_to", ""))
    search = request.GET.get("search", "")
    feed = superadmin_audit_feed(category=category, date_from=date_from, date_to=date_to,
                                  search=search, page=1, page_size=100000)

    class _Echo:
        def write(self, value):
            return value

    def rows_gen():
        writer = csv.writer(_Echo())
        yield writer.writerow(["Время", "Актор", "Действие", "Объект", "IP", "Результат"])
        for r in feed["rows"]:
            yield writer.writerow([
                r["created_at"].strftime("%d.%m.%Y %H:%M:%S"), r["actor_label"] or "—",
                r["action_label"], r["object_repr"] or "—", r["ip"] or "—",
                "Успех" if r["result"] == "success" else "Отказ",
            ])

    resp = StreamingHttpResponse(rows_gen(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="audit_events.csv"'
    return resp


@login_required
def newui_superadmin_users(request):
    """AJAX: сотрудники по ВСЕЙ платформе (кросс-клиниково) — вкладка
    «Пользователи». Поиск по имени/логину/телефону, серверная пагинация
    (apps.tenancy.unscoped() — тот же приём, что и в _newui_superadmin_data,
    без него User.objects виден только по текущей клинике)."""
    from django.http import JsonResponse
    from django.core.paginator import Paginator
    from django.db.models import Q
    if not request.user.is_superadmin:
        return JsonResponse({"error": "Доступно только суперадмину"}, status=403)
    from apps.tenancy import unscoped
    from .models import User
    search = request.GET.get("search", "").strip()
    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        page = 1
    with unscoped():
        qs = User.objects.select_related("role", "clinic").order_by("name")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(login__icontains=search) | Q(phone__icontains=search))
        paginator = Paginator(qs, 50)
        page_obj = paginator.get_page(page)
        rows = [{
            "id": u.pk, "name": u.name, "login": u.login,
            "role": u.role.display_name if u.role else "—",
            "clinicName": u.clinic.name if u.clinic else "—",
            "clinicId": u.clinic_id,
            "isActive": u.is_active,
            "phone": u.phone,
        } for u in page_obj]
    return JsonResponse({
        "rows": rows, "total": paginator.count,
        "page": page_obj.number, "num_pages": paginator.num_pages,
    })


@login_required
def newui_clinic_create(request):
    """AJAX: создание клиники из новой супер-админ-панели. В отличие от
    остальных мутаций этой страницы (которые идут через старые POST-вьюхи
    старого интерфейса, res.redirected → flashAndReload — там редирект всегда
    означает успех), у создания клиники есть реальные ошибки валидации
    (пустые поля, занятый логин), которые старая вьюха (superadmin_panel)
    показывает через messages И ВСЁ РАВНО редиректит — так что «редирект =
    успех» здесь не работает. Поэтому — отдельный JSON-эндпоинт, переиспользующий
    ту же _create_clinic(), а не дублирующий её."""
    from django.http import JsonResponse
    from apps.users.views import _create_clinic
    if not request.user.is_superadmin:
        return JsonResponse({"error": "Доступно только суперадмину"}, status=403)
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    do_seed = request.POST.get("clinic_seed", "1") != "0"
    try:
        clinic, admin_user, seed_result = _create_clinic(
            request.POST.get("clinic_name", ""),
            request.POST.get("clinic_admin_login", ""),
            request.POST.get("clinic_admin_password", ""),
            request.POST.get("clinic_admin_name", ""),
            do_seed,
            request=request,
        )
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    from django.conf import settings as dj_settings
    app_host = getattr(dj_settings, "APP_HOST", "app.sadaf.kg")
    return JsonResponse({
        "ok": True, "id": clinic.pk, "name": clinic.name, "slug": clinic.slug,
        "adminLogin": admin_user.login,
        "loginUrl": f"https://{app_host}/login/?clinic={clinic.slug}",
    })


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
def newui_notifications(request):
    return _render(request, "notifications", "notifications.html", {"notificationsData": _newui_notifications_data(request)})


@login_required
def newui_audit(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or getattr(request.user, "clinic", None)
    return _render(request, "audit", "audit.html", {"auditEvents": _newui_audit_data(clinic)})


@login_required
def audit_revert(request, model, history_id):
    """Откатить пациента/приём к состоянию на момент выбранной исторической
    записи (django-simple-history: hist.instance — реконструированный по
    historical-полям экземпляр, .save() перезаписывает им текущую запись —
    стандартный для этой библиотеки способ отката). Необратимо перезаписывает
    текущее состояние объекта — поэтому строго только для
    суперадминистратора, без более тонкого права (риск слишком велик, чтобы
    давать его через обычную ролевую систему)."""
    from django.http import JsonResponse

    if request.method != "POST":
        return JsonResponse({"error": "Метод не поддерживается"}, status=405)
    if not request.user.is_superadmin:
        return JsonResponse({"error": "Доступно только суперадминистратору"}, status=403)

    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    from apps.tenancy import get_current_clinic

    model_map = {"patient": Patient, "treatment": Treatment}
    Model = model_map.get(model)
    if Model is None:
        return JsonResponse({"error": "Неизвестный тип записи"}, status=400)

    clinic = get_current_clinic()
    qs = Model.history.all()
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    hist = qs.filter(history_id=history_id).first()
    if hist is None:
        return JsonResponse({"error": "Запись в истории не найдена"}, status=404)
    if hist.history_type == "-":
        # У записи «Удаление» нет корректного «предыдущего состояния» объекта
        # для восстановления через этот путь — выбирайте более раннюю запись.
        return JsonResponse({"error": "Нельзя откатить к записи об удалении — выберите более раннюю запись"}, status=400)
    try:
        hist.instance.save()
    except Exception as e:
        return JsonResponse({"error": f"Не удалось откатить: {e}"}, status=500)
    return JsonResponse({"ok": True})


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
    return _render(request, "messages", "messages.html", {
        "messagesData": _newui_messages_data(clinic),
        # Поиск в списке бесед должен находить ЛЮБОГО пациента, не только
        # тех, у кого уже есть переписка (messagesData.clients) — иначе
        # начать НОВЫЙ чат из поиска было невозможно (жалоба: «при поиске
        # сделай список пациентов, нажав на него могут отправлять
        # сообщения»). patientsList не был частью _shared_options — на этой
        # странице до сих пор был пуст.
        "patients": _newui_patients_data(),
    })


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
