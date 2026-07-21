from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from django.views.decorators.http import require_POST

from .models import Patient, Tag, LeadSource, SharedPhoneNumber
from .forms import PatientForm
from apps.treatments.models import Treatment, TreatmentCure
from apps.finance.models import Payment


@login_required
def patient_list(request):
    from datetime import date, timedelta
    from django.db.models import Sum
    from decimal import Decimal

    qs = Patient.objects.select_related("branch", "source", "primary_doctor").prefetch_related("tags")
    G = request.GET
    q = G.get("q", "")
    branch_id = G.get("branch", "")
    doctor_id = G.get("doctor", "")
    gender = G.get("gender", "")
    source_id = G.get("source", "")
    tag_id = G.get("tag", "")
    blood = G.get("blood", "")
    debt = G.get("debt", "")
    insurance = G.get("insurance", "")
    allergy_f = G.get("allergy", "")
    birth_from = G.get("birth_from", "")
    birth_to = G.get("birth_to", "")
    age_min = G.get("age_min", "")
    age_max = G.get("age_max", "")
    bmonth = G.get("bmonth", "")
    reg_from = G.get("reg_from", "")
    reg_to = G.get("reg_to", "")
    pin_f = G.get("pin", "")
    dupes_f = G.get("dupes", "")

    today = date.today()
    week_ago = today - timedelta(days=7)

    def years_ago(n):
        try:
            return today.replace(year=today.year - n)
        except ValueError:  # 29 февраля
            return today.replace(year=today.year - n, day=28)

    if q:
        # Полное имя лежит в разных полях (Фамилия/Имя/Отчество), поэтому запрос вида
        # "Турдубеков Динара" разбиваем на слова и требуем, чтобы КАЖДОЕ слово нашлось
        # хоть в одном из полей — иначе "Фамилия Имя" целиком нигде не совпадёт.
        words = q.split()
        for word in words:
            qs = qs.filter(
                Q(first_name__icontains=word)
                | Q(last_name__icontains=word)
                | Q(middle_name__icontains=word)
                | Q(phone__icontains=word)
                | Q(phone2__icontains=word)
            )
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if doctor_id:
        qs = qs.filter(primary_doctor_id=doctor_id)
    if gender:
        qs = qs.filter(gender=gender)
    if source_id:
        qs = qs.filter(source_id=source_id)
    if tag_id:
        qs = qs.filter(tags__id=tag_id)
    if blood:
        qs = qs.filter(blood_group=blood)
    # Точный пересчёт долгов по агрегатам (баланс-поле может быть устаревшим)
    from collections import defaultdict
    inc_map, ref_map, billed_map = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    for r in Payment.objects.filter(type="income").values("patient_id").annotate(s=Sum("amount")):
        inc_map[r["patient_id"]] = r["s"] or Decimal(0)
    for r in Payment.objects.filter(type="refund").values("patient_id").annotate(s=Sum("amount")):
        ref_map[r["patient_id"]] = r["s"] or Decimal(0)
    for r in (Treatment.objects.exclude(status__in=["cancelled", "draft"])
              .values("patient_id").annotate(t=Sum("total_amount"), d=Sum("discount"))):
        billed_map[r["patient_id"]] = (r["t"] or Decimal(0)) - (r["d"] or Decimal(0))
    debt_map = {}
    over_ids = set()
    for pid in set(inc_map) | set(ref_map) | set(billed_map):
        bal = inc_map[pid] - ref_map[pid] - billed_map[pid]
        if bal < 0:
            debt_map[pid] = -bal
        elif bal > 0:
            over_ids.add(pid)
    debtor_ids = set(debt_map)

    if debt == "yes":
        qs = qs.filter(pk__in=debtor_ids)
    elif debt == "no":
        qs = qs.exclude(pk__in=debtor_ids)
    elif debt == "over":
        qs = qs.filter(pk__in=over_ids)
    if insurance == "yes":
        qs = qs.filter(Q(insurance__isnull=False) | ~Q(insurance_policy=""))
    elif insurance == "no":
        qs = qs.filter(insurance__isnull=True, insurance_policy="")
    if allergy_f == "yes":
        qs = qs.exclude(Q(allergy__isnull=True) | Q(allergy=""))
    elif allergy_f == "no":
        qs = qs.filter(Q(allergy__isnull=True) | Q(allergy=""))
    if birth_from:
        qs = qs.filter(birth_date__gte=birth_from)
    if birth_to:
        qs = qs.filter(birth_date__lte=birth_to)
    if age_min.isdigit():
        qs = qs.filter(birth_date__lte=years_ago(int(age_min)))
    if age_max.isdigit():
        qs = qs.filter(birth_date__gt=years_ago(int(age_max) + 1))
    if bmonth.isdigit():
        qs = qs.filter(birth_date__month=int(bmonth))
    if reg_from:
        qs = qs.filter(created_at__date__gte=reg_from)
    if reg_to:
        qs = qs.filter(created_at__date__lte=reg_to)
    if pin_f == "yes":
        qs = qs.exclude(pin="")
    elif pin_f == "no":
        qs = qs.filter(pin="")
    # Набор телефонов, встречающихся у нескольких пациентов — нужен всегда (не
    # только при фильтре ?dupes=1), чтобы показывать кнопку «Есть в базе» только
    # у реальных дублей, а не у каждого пациента подряд.
    from django.db.models import Count as _Count
    confirmed_shared = set(SharedPhoneNumber.objects.values_list("phone_norm", flat=True))
    dupe_phones = set(
        Patient.objects.exclude(phone_norm="").exclude(phone_norm__in=confirmed_shared)
        .values("phone_norm").annotate(c=_Count("id")).filter(c__gt=1)
        .values_list("phone_norm", flat=True)
    )
    if dupes_f:
        qs = qs.filter(phone_norm__in=dupe_phones)
    qs = qs.distinct()

    # Пагинация — список рос (200+ пациентов), рендерить всех разом не годится.
    from django.core.paginator import Paginator
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(G.get("page"))
    qd = request.GET.copy()
    qd.pop("page", None)
    page_qs = qd.urlencode()

    # Stats
    all_count = Patient.objects.count()
    new_count = Patient.objects.filter(created_at__date__gte=week_ago).count()

    # Birthday in next 7 days
    birthday_count = 0
    for p in Patient.objects.exclude(birth_date=None).values_list("birth_date", flat=True):
        try:
            bd = p.replace(year=today.year)
        except ValueError:
            bd = p.replace(year=today.year, day=28)
        if today <= bd <= today + timedelta(days=7):
            birthday_count += 1

    # долги — из точного пересчёта (см. выше debt_map)
    debtors_count = len(debt_map)
    debtors_total = sum(debt_map.values()) if debt_map else Decimal(0)

    with_pin_count = Patient.objects.exclude(pin="").count()
    without_pin_count = all_count - with_pin_count

    from apps.users.models import Branch, clinic_doctors
    from apps.tenancy import get_current_clinic
    branches = Branch.objects.all()

    blood_groups = list(
        Patient.objects.exclude(blood_group="").order_by("blood_group")
        .values_list("blood_group", flat=True).distinct()
    )

    # Текущие значения фильтров (для повторного выбора в форме) + счётчик активных
    f = {
        "branch": branch_id, "doctor": doctor_id, "gender": gender, "source": source_id,
        "tag": tag_id, "blood": blood, "debt": debt, "insurance": insurance,
        "allergy": allergy_f, "birth_from": birth_from, "birth_to": birth_to,
        "age_min": age_min, "age_max": age_max, "bmonth": bmonth,
        "reg_from": reg_from, "reg_to": reg_to, "pin": pin_f, "dupes": dupes_f,
    }
    adv_count = sum(1 for v in f.values() if v)

    return render(request, "patients/list.html", {
        "patients": page_obj,
        "page_obj": page_obj,
        "page_qs": page_qs,
        "q": q,
        "sources": LeadSource.objects.filter(is_active=True),
        "branches": branches,
        "doctors": clinic_doctors(get_current_clinic()),
        "sel_doctor": doctor_id,
        "genders": Patient.GENDER_CHOICES,
        "tags": Tag.objects.all(),
        "blood_groups": blood_groups,
        "months": [
            (1, "Январь"), (2, "Февраль"), (3, "Март"), (4, "Апрель"),
            (5, "Май"), (6, "Июнь"), (7, "Июль"), (8, "Август"),
            (9, "Сентябрь"), (10, "Октябрь"), (11, "Ноябрь"), (12, "Декабрь"),
        ],
        "f": f,
        "adv_count": adv_count,
        "result_count": paginator.count,
        "all_count": all_count,
        "new_count": new_count,
        "birthday_count": birthday_count,
        "today_month": today.month,
        "debtors_count": debtors_count,
        "debtors_total": abs(debtors_total),
        "with_pin_count": with_pin_count,
        "without_pin_count": without_pin_count,
        "dupe_phones": dupe_phones,
    })


@login_required
def patient_merge_search(request, pk):
    """AJAX: найти возможных «оригиналов» этого пациента среди остальных — по
    нормализованному телефону или по ФИО. Используется кнопкой «Есть в базе»
    на пациентах без ИИН (обычно созданных автоматически с сайта)."""
    from django.http import JsonResponse
    from .models import normalize_phone
    patient = get_object_or_404(Patient, pk=pk)
    pnorm = normalize_phone(patient.phone)
    qs = Patient.objects.exclude(pk=patient.pk)
    if pnorm:
        cand = list(qs.filter(phone_norm=pnorm))
    else:
        cand = []
    if not cand and patient.last_name.strip():
        cand = list(qs.filter(
            last_name__iexact=patient.last_name.strip(),
            first_name__iexact=patient.first_name.strip(),
        ))
    rows = [{
        "id": c.pk, "number": c.display_number, "name": c.full_name,
        "phone": c.phone, "birth_date": c.birth_date.strftime("%d.%m.%Y") if c.birth_date else "",
        "treatments": Treatment.all_objects.filter(patient=c, is_deleted=False).count(),
    } for c in cand]
    return JsonResponse({"ok": True, "candidates": rows})


@login_required
@require_POST
def patient_merge_confirm(request, pk):
    """Объединить двух пациентов — переносит ВСЕ связанные записи (приёмы, платежи,
    записи, файлы и т.д.) и мягко удаляет один из них.

    Направление объединения НЕ зависит от того, на какой из двух карточек была
    нажата кнопка «Есть в базе»: всегда остаётся более СТАРАЯ карточка (раньше
    созданная — обычно с уже накопленной историей/долгом), а более новая
    переносится в неё и удаляется. Иначе персонал мог случайно удалить как раз
    ту карточку, где уже была реальная история, оставив пустую.
    """
    a = get_object_or_404(Patient, pk=pk)
    b = get_object_or_404(Patient, pk=request.POST.get("target"))
    if a.pk == b.pk:
        messages.error(request, _("Нельзя объединить пациента с самим собой"))
        return redirect("patient_detail", pk=a.pk)
    # Кто старше — по дате создания, а при совпадении (частый случай в тестах/быстрых
    # массовых импортах, где created_at совпадает до секунды) — по pk как тайбрейкеру.
    target, source = (a, b) if (a.created_at, a.pk) <= (b.created_at, b.pk) else (b, a)
    merge_patients(source, target, request.user)
    messages.success(request, _(
        "Пациент №%(s)s объединён с №%(t)s — вся история (приёмы, платежи, записи) перенесена."
    ) % {"s": source.display_number, "t": target.display_number})
    return redirect("patient_detail", pk=target.pk)


@login_required
@require_POST
def patient_mark_not_duplicate(request, pk):
    """Подтвердить, что пациент с этим номером телефона — НЕ дубль (например,
    номер общий у родственников). Запоминаем номер, чтобы предупреждение
    «Есть в базе» и бейдж в сайдбаре больше не показывались для него."""
    patient = get_object_or_404(Patient, pk=pk)
    from .models import normalize_phone
    pnorm = normalize_phone(patient.phone)
    if pnorm:
        SharedPhoneNumber.objects.get_or_create(phone_norm=pnorm, defaults={"noted_by": request.user})
        messages.success(request, _("Отмечено: этот номер телефона общий для разных пациентов — предупреждение больше не будет показываться."))
    referer = request.META.get("HTTP_REFERER")
    if referer:
        return redirect(referer)
    return redirect("patient_detail", pk=patient.pk)


def merge_patients(source, target, user=None):
    """Перенести ВСЕ связанные записи source → target и мягко удалить source.
    Затрагивает: приёмы, ЭМК, планы лечения, зубную карту, платежи, авансы,
    записи на приём, назначенные лекарства, WhatsApp-переписку, заказы/гарантии
    техникам, теги. Всё в одной транзакции — либо переносится целиком, либо
    ничего (при ошибке)."""
    from django.db import transaction
    from apps.treatments.models import Treatment
    from apps.treatments.models_emr import MedicalRecord
    from apps.treatments.models_plan import TreatmentPlan
    from apps.treatments.models_teeth import ToothCondition
    from apps.finance.models import Payment
    from apps.finance.models import PatientAdvance
    from apps.appointments.models import Appointment
    from apps.medicines.models import PatientMedicine
    from apps.notifications.models import WaMessage
    from apps.technicians.models import TechnicianTask, TechnicianWarrantyCase

    with transaction.atomic():
        Treatment.all_objects.filter(patient=source).update(patient=target)
        MedicalRecord.objects.filter(patient=source).update(patient=target)
        TreatmentPlan.objects.filter(patient=source).update(patient=target)
        ToothCondition.objects.filter(patient=source).update(patient=target)
        Payment.all_clinics.filter(patient=source).update(patient=target)
        PatientAdvance.objects.filter(patient=source).update(patient=target)
        Appointment.all_objects.filter(patient=source).update(patient=target)
        PatientMedicine.objects.filter(patient=source).update(patient=target)
        WaMessage.all_clinics.filter(patient=source).update(patient=target)
        TechnicianTask.all_clinics.filter(patient=source).update(patient=target)
        TechnicianWarrantyCase.all_clinics.filter(patient=source).update(patient=target)
        for tag in source.tags.all():
            target.tags.add(tag)
        if not target.pin and source.pin:
            target.pin = source.pin
        if not target.address and source.address:
            target.address = source.address
        target.save()
        source.soft_delete(user)
        target.recalc_balance()
    return target


@login_required
def patient_create(request):
    form = PatientForm(request.POST or None)
    if form.is_valid():
        patient = form.save(commit=False)
        # Дубликат: совпадают ФИО И телефон → не создаём (другой телефон — создаём)
        from .models import normalize_phone
        pnorm = normalize_phone(patient.phone)
        if pnorm:
            dup = (Patient.objects.filter(
                last_name__iexact=patient.last_name.strip(),
                first_name__iexact=patient.first_name.strip())
                .filter(Q(phone__contains=pnorm) | Q(phone2__contains=pnorm)))
            dup = [p for p in dup if normalize_phone(p.phone) == pnorm or normalize_phone(p.phone2) == pnorm]
            if dup:
                messages.error(request, _("Пациент с таким ФИО и телефоном уже существует (№%(n)s). Открыт существующий.") % {"n": dup[0].display_number})
                return redirect("patient_detail", pk=dup[0].pk)
        patient.created_by = request.user
        patient.save()
        form.save_m2m()
        messages.success(request, _("Пациент добавлен"))
        bl = patient.blacklist_entry
        if bl:
            messages.warning(request, _("⛔ Внимание: номер в общем чёрном списке%(r)s") % {
                "r": (": " + bl.reason) if bl.reason else ""})
        return redirect("patient_detail", pk=patient.pk)
    return render(request, "patients/form.html", {"form": form, "title": _("Новый пациент")})


@login_required
def patient_detail(request, pk):
    patient = get_object_or_404(Patient.objects.prefetch_related("tags"), pk=pk)
    from django.db.models import Case, When, IntegerField, Value
    # Порядок: запланированные → в процессе → завершённые → оплаченные → отменённые
    status_order = Case(
        When(status="planned", then=Value(0)),
        When(status="in_progress", then=Value(1)),
        When(status="completed", then=Value(2)),
        When(status="paid", then=Value(3)),
        When(status="cancelled", then=Value(4)),
        default=Value(9), output_field=IntegerField(),
    )
    # all_objects/all_clinics — приёмы и платежи пациента показываем независимо от того,
    # какую клинику сейчас просматривает суперадмин (иначе они "пропадают" при переключении).
    treatments = Treatment.all_objects.filter(patient=patient, is_deleted=False).select_related(
        "doctor", "branch"
    ).prefetch_related(
        "cures__service", "cures__doctor", "files"
    ).annotate(_status_order=status_order).order_by("_status_order", "-created_at")
    payments = Payment.all_clinics.filter(patient=patient).select_related("received_by").order_by("-created_at")
    from apps.services.models import Service, ServiceCategory
    from apps.users.models import User as StaffUser
    _svcs = Service.objects.filter(is_active=True).select_related("category").order_by("category__sort_order","name").values(
        "id", "name", "price", "category__name", "category__id"
    )
    all_services_json = [
        {"id": s["id"], "name": s["name"], "price": float(s["price"]),
         "category__name": s["category__name"] or "", "category__id": s["category__id"] or 0}
        for s in _svcs
    ]
    service_categories_json = list(ServiceCategory.objects.values("id", "name"))
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic
    doctors = clinic_doctors(get_current_clinic())
    treatment_plans = patient.treatment_plans.select_related("doctor").prefetch_related(
        "items__service", "items__doctor"
    ).order_by("-created_at")
    # Зубная карта: справочник статусов + сохранённые состояния зубов пациента
    from apps.treatments.models_teeth import ToothStatus, ToothCondition, DEFAULT_TOOTH_STATUSES
    if not ToothStatus.objects.exists():
        for i, (code, name, color) in enumerate(DEFAULT_TOOTH_STATUSES):
            ToothStatus.objects.create(code=code, name=name, color=color, sort_order=i)
    tooth_statuses_json = [{"id": s.id, "code": s.code, "name": s.name, "color": s.color}
                           for s in ToothStatus.objects.all()]
    tooth_conditions_json = {
        str(tc.tooth_number): {"status_id": tc.status_id,
                               "color": tc.status.color if tc.status else "",
                               "name": tc.status.name if tc.status else ""}
        for tc in ToothCondition.objects.filter(patient=patient).select_related("status")
    }
    # Лабораторные работы по зубам (техник + гарантия) — для подсказки в зубной карте
    tooth_lab_json = {}
    for c in (TreatmentCure.objects.filter(treatment__patient=patient, technician__isnull=False)
              .select_related("technician", "service").order_by("-id")):
        key = str(c.tooth_number or "").strip()
        if not key or key in tooth_lab_json:
            continue
        parts = [c.service.name, f"техник: {c.technician.name}"]
        if c.technician.lab_name:
            parts.append(c.technician.lab_name)
        if c.warranty_until:
            parts.append(f"гарантия до {c.warranty_until:%d.%m.%Y}")
        tooth_lab_json[key] = " · ".join(parts)
    from apps.settings_clinic.models_documents import DocumentTemplate
    doc_templates = DocumentTemplate.objects.filter(is_active=True)
    from apps.users.models import Branch
    all_branches = Branch.objects.filter(is_active=True)
    main_branch = all_branches.filter(is_main=True).first() or all_branches.first()

    # WhatsApp: шаблоны (с подстановкой данных пациента) + статус интеграции
    from apps.notifications.models import MessageTemplate
    from apps.notifications.whatsapp import render_message, wa_enabled, seed_default_templates
    if not MessageTemplate.objects.exists():
        try:
            seed_default_templates()
        except Exception:
            pass
    wa_templates = [
        {"id": t.pk, "name": t.name, "kind": t.get_kind_display(),
         "body": render_message(t.body, patient=patient)}
        for t in MessageTemplate.objects.filter(is_active=True)
    ]
    return render(request, "patients/detail.html", {
        "doc_templates": doc_templates,
        "patient": patient,
        "treatments": treatments,
        "payments": payments,
        "treatment_plans": treatment_plans,
        "all_services_json": all_services_json,
        "tooth_statuses_json": tooth_statuses_json,
        "tooth_conditions_json": tooth_conditions_json,
        "tooth_lab_json": tooth_lab_json,
        "service_categories_json": service_categories_json,
        "service_categories": ServiceCategory.objects.order_by("name"),
        "doctors": doctors,
        "all_branches": all_branches,
        "main_branch": main_branch,
        "wa_templates": wa_templates,
        "wa_enabled": wa_enabled(),
    })


@login_required
def patient_notify(request, pk):
    """Отдельная страница: отправить пациенту сообщение (WhatsApp или Telegram)."""
    patient = get_object_or_404(Patient, pk=pk)
    from apps.notifications.whatsapp import wa_send_text, wa_enabled, render_message
    from apps.notifications.telegram import tg_send_text, tg_enabled
    from apps.notifications.models import MessageTemplate, WaMessage

    if request.method == "POST":
        text = (request.POST.get("text") or "").strip()
        channel = request.POST.get("channel") or "wa"
        if not text:
            messages.error(request, _("Введите текст сообщения"))
        elif channel == "tg":
            if not patient.telegram_chat_id:
                messages.error(request, _("Пациент ещё не привязал Telegram (не нажимал Start у бота)"))
            elif not tg_enabled():
                messages.error(request, _("Telegram не настроен"))
            else:
                ok = tg_send_text(patient.telegram_chat_id, text)
                WaMessage.objects.create(patient=patient, direction="out", channel="tg",
                                         phone=str(patient.telegram_chat_id),
                                         body=text, sent_by=request.user, ok=ok)
                if ok:
                    messages.success(request, _("Сообщение отправлено в Telegram"))
                    return redirect("patient_notify", pk=pk)
                messages.error(request, _("Не удалось отправить в Telegram"))
        elif not patient.phone:
            messages.error(request, _("У пациента нет телефона"))
        elif not wa_enabled():
            messages.error(request, _("WhatsApp не настроен"))
        else:
            ok = wa_send_text(patient.phone, text)
            WaMessage.objects.create(patient=patient, direction="out", channel="wa", phone=patient.phone,
                                     body=text, sent_by=request.user, ok=ok)
            if ok:
                messages.success(request, _("Сообщение отправлено"))
                return redirect("patient_notify", pk=pk)
            messages.error(request, _("Не удалось отправить (проверьте номер/инстанс)"))

    if not MessageTemplate.objects.exists():
        from apps.notifications.whatsapp import seed_default_templates
        try:
            seed_default_templates()
        except Exception:
            pass
    # ближайший будущий приём пациента — для подстановки {дата}/{время}/{врач} в шаблоны
    from apps.appointments.models import Appointment
    from django.utils import timezone
    next_appt = (Appointment.objects.filter(patient=patient, start_at__gte=timezone.now())
                 .exclude(status__in=["cancelled", "no_show"]).order_by("start_at").first())
    tpls = [{"name": t.name, "body": render_message(t.body, patient=patient, appt=next_appt)}
            for t in MessageTemplate.objects.filter(is_active=True)]
    WaMessage.all_clinics.filter(patient=patient, direction="in", read=False).update(read=True)
    history = list(WaMessage.all_clinics.filter(patient=patient).order_by("created_at")[:300])
    default_channel = request.GET.get("channel") or ("tg" if (patient.telegram_chat_id and not patient.phone) else "wa")
    return render(request, "patients/notify.html", {
        "patient": patient, "wa_templates": tpls, "wa_enabled": wa_enabled(),
        "tg_enabled": tg_enabled(), "has_telegram": bool(patient.telegram_chat_id),
        "default_channel": default_channel,
        "wa_history": history, "last_id": history[-1].id if history else 0,
    })


@login_required
def patient_wa_messages(request, pk):
    """JSON новых сообщений чата для авто-обновления."""
    from django.http import JsonResponse
    from django.utils import timezone
    patient = get_object_or_404(Patient, pk=pk)
    from apps.notifications.models import WaMessage
    after = request.GET.get("after") or 0
    try:
        after = int(after)
    except (TypeError, ValueError):
        after = 0
    qs = WaMessage.all_clinics.filter(patient=patient, id__gt=after).order_by("id")[:100]
    msgs = [{"id": m.id, "dir": m.direction, "body": m.body, "ok": m.ok, "channel": m.channel,
             "media_url": (m.media_file.url if m.media_file else ""), "media_type": m.media_type,
             "by": m.sent_by.name if m.sent_by else "",
             "time": timezone.localtime(m.created_at).strftime("%d.%m %H:%M")} for m in qs]
    return JsonResponse({"messages": msgs})


@login_required
def patient_export(request):
    from .excel_io import export_patients_xlsx
    return export_patients_xlsx()


@login_required
@require_POST
def patient_import(request):
    from .excel_io import import_patients_xlsx
    f = request.FILES.get("file")
    if not f:
        messages.warning(request, _("Файл не выбран"))
        return redirect("patient_list")
    try:
        created, updated, errors = import_patients_xlsx(f)
        messages.success(request, _("Импорт: добавлено %(c)d, обновлено %(u)d") % {"c": created, "u": updated})
        if errors:
            messages.warning(request, "; ".join(errors[:5]))
    except Exception as e:
        messages.error(request, _("Ошибка импорта: %(e)s") % {"e": str(e)})
    return redirect("patient_list")


@login_required
def blacklist_view(request):
    """Общий чёрный список (по номеру телефона). Просмотр + добавить/удалить."""
    from .models import BlacklistEntry
    from apps.tenancy import get_current_clinic
    cur = get_current_clinic()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            phone = (request.POST.get("phone") or "").strip()
            if phone:
                BlacklistEntry.objects.create(
                    phone=phone, name=(request.POST.get("name") or "").strip(),
                    reason=(request.POST.get("reason") or "").strip(),
                    clinic=cur, added_by=request.user,
                )
                messages.success(request, _("Добавлено в чёрный список"))
        elif action == "remove":
            # Убрать можно только запись СВОЕЙ клиники. Флаги других клиник остаются —
            # у каждой клиники свой флаг по номеру. Суперадмин (cur=None) может убрать любую.
            qs = BlacklistEntry.objects.filter(pk=request.POST.get("id"))
            if cur is not None:
                qs = qs.filter(clinic=cur)
            if qs.delete()[0]:
                messages.success(request, _("Убрано из чёрного списка (только для вашей клиники)"))
            else:
                messages.error(request, _("Эту запись добавила другая клиника — убрать её может только она."))
        elif action == "edit_reason":
            # Изменить причину может только клиника, добавившая запись (или суперадмин).
            qs = BlacklistEntry.objects.filter(pk=request.POST.get("id"))
            if cur is not None:
                qs = qs.filter(clinic=cur)
            obj = qs.first()
            if obj:
                obj.reason = (request.POST.get("reason") or "").strip()
                obj.name = (request.POST.get("name") or obj.name).strip()
                obj.save(update_fields=["reason", "name"])
                messages.success(request, _("Причина обновлена"))
            else:
                messages.error(request, _("Эту запись добавила другая клиника — изменить её может только она."))
        return redirect("blacklist")
    q = (request.GET.get("q") or "").strip()
    entries = list(BlacklistEntry.objects.select_related("clinic", "added_by"))
    if q:
        ql = q.lower()
        entries = [e for e in entries if ql in (e.phone or "").lower()
                   or ql in (e.name or "").lower() or ql in (e.reason or "").lower()]

    # Кросс-клиниковая сводка по каждому номеру: где есть пациент, долг, кол-во приёмов
    from decimal import Decimal
    from .models import normalize_phone
    from django.db.models import Sum, Count
    for e in entries:
        norm = e.phone_norm
        pts = (Patient.all_objects.select_related("clinic")
               .filter(Q(phone__contains=norm) | Q(phone2__contains=norm)))
        rows, total = [], Decimal(0)
        for pt in pts:
            if normalize_phone(pt.phone) != norm and normalize_phone(pt.phone2) != norm:
                continue
            agg = (Treatment.all_objects.filter(patient_id=pt.pk, is_deleted=False)
                   .exclude(status="cancelled")
                   .aggregate(tot=Sum("total_amount"), disc=Sum("discount"), cnt=Count("id")))
            billed = (agg["tot"] or Decimal(0)) - (agg["disc"] or Decimal(0))
            # balance < 0 => пациент должен; долг = -balance
            debt = max(Decimal(0), -(pt.balance or Decimal(0)))
            total += debt
            rows.append({"clinic": pt.clinic.name if pt.clinic else "—",
                         "patient_id": pt.pk, "name": pt.full_name,
                         "treatments": agg["cnt"] or 0, "billed": billed, "debt": debt})
        e.cross = rows
        e.total_debt = total
        e.can_remove = (cur is None) or (e.clinic_id == cur.id)
    return render(request, "patients/blacklist.html", {"entries": entries, "q": q})


@login_required
def blacklist_check(request):
    """AJAX: проверить номер по общему чёрному списку. ?phone=... → {match, reason, ...}."""
    from django.http import JsonResponse
    from .models import BlacklistEntry, normalize_phone
    norm = normalize_phone(request.GET.get("phone", ""))
    if not norm:
        return JsonResponse({"match": False})
    e = BlacklistEntry.objects.filter(phone_norm=norm).select_related("clinic").first()
    if not e:
        return JsonResponse({"match": False})
    return JsonResponse({"match": True, "reason": e.reason or "", "name": e.name or "",
                         "clinic": e.clinic.name if e.clinic else "",
                         "date": e.created_at.strftime("%d.%m.%Y")})


@login_required
@require_POST
def patient_blacklist_toggle(request, pk):
    """Быстро добавить/убрать пациента из общего ЧС (из карточки)."""
    from .models import BlacklistEntry, normalize_phone
    from apps.tenancy import get_current_clinic
    patient = get_object_or_404(Patient, pk=pk)
    existing = patient.blacklist_entry
    if existing:
        existing.delete()
        messages.success(request, _("Пациент убран из чёрного списка"))
    elif patient.phone:
        BlacklistEntry.objects.create(
            phone=patient.phone, name=patient.full_name,
            reason=(request.POST.get("reason") or "").strip(),
            clinic=get_current_clinic(), added_by=request.user,
        )
        messages.success(request, _("Пациент добавлен в чёрный список"))
    return redirect("patient_detail", pk=pk)


def _visits_journal_allowed(user):
    """Кому виден общий журнал: всегда директор/админ/суперадмин; персоналу — если разрешил директор."""
    if user.is_superadmin or getattr(user, "is_admin", False) or getattr(user, "is_admin_main", False):
        return True
    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()
    return bool(getattr(cs, "visits_journal_staff", True))


@login_required
def visits_journal(request):
    """Общий журнал посещений клиники: выбрать пациента, +посещение, сводка кто/сколько/когда."""
    from .models import PatientVisit
    from django.utils import timezone
    if not _visits_journal_allowed(request.user):
        messages.error(request, _("Журнал посещений скрыт администратором"))
        return redirect("/")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "toggle_visibility" and (request.user.is_superadmin or request.user.is_admin_main):
            from apps.settings_clinic.models import ClinicSettings
            cs = ClinicSettings.get()
            cs.visits_journal_staff = not cs.visits_journal_staff
            cs.save(update_fields=["visits_journal_staff", "updated_at"])
            return redirect("visits_journal")
        if action == "delete":
            PatientVisit.objects.filter(pk=request.POST.get("id")).delete()
            messages.success(request, _("Посещение удалено"))
            return redirect("visits_journal")
        if action == "add":
            p = Patient.objects.filter(pk=request.POST.get("patient")).first()
            if p:
                when = request.POST.get("visited_at") or None
                note = (request.POST.get("reason") or "").strip()
                svc_ids = request.POST.getlist("services")
                if svc_ids:
                    from apps.services.models import Service
                    names = list(Service.objects.filter(pk__in=svc_ids).values_list("name", flat=True))
                    if names:
                        note = (note + ("\n" if note else "") + "Услуги: " + ", ".join(names)).strip()
                PatientVisit.objects.create(
                    patient=p, visited_at=(when or timezone.now()), note=note,
                    source=PatientVisit.SOURCE_MANUAL, created_by=request.user,
                )
                messages.success(request, _("Посещение отмечено: %(n)s") % {"n": p.full_name})
            return redirect("visits_journal")

    q = (request.GET.get("q") or "").strip()
    visit = request.GET.get("visit", "")  # '', primary (1 визит), secondary (2+)
    from django.db.models import Count, Max
    agg = list(PatientVisit.objects.values("patient")
               .annotate(cnt=Count("id"), last=Max("visited_at")).order_by("-last"))
    pat_ids = [a["patient"] for a in agg]
    pmap = {p.pk: p for p in Patient.objects.filter(pk__in=pat_ids)}
    primary_count = sum(1 for a in agg if a["cnt"] == 1)   # первичные: были 1 раз
    secondary_count = sum(1 for a in agg if a["cnt"] > 1)  # вторичные: повторные пациенты
    rows = []
    for a in agg:
        p = pmap.get(a["patient"])
        if not p:
            continue
        if q and q.lower() not in p.full_name.lower() and q not in (p.phone or ""):
            continue
        if visit == "primary" and a["cnt"] != 1:
            continue
        if visit == "secondary" and a["cnt"] <= 1:
            continue
        rows.append({"patient": p, "count": a["cnt"], "last": a["last"]})
    today = timezone.localdate()
    visits_today = PatientVisit.objects.filter(visited_at__date=today).count()
    from apps.services.models import Service
    return render(request, "patients/visits_journal.html", {
        "rows": rows, "q": q, "visit": visit,
        "patients": Patient.objects.order_by("last_name", "first_name"),
        "services": Service.objects.filter(is_active=True).order_by("name"),
        "total_visits": PatientVisit.objects.count(),
        "visits_today": visits_today,
        "uniq_patients": len(pat_ids),
        "primary_count": primary_count,
        "secondary_count": secondary_count,
        "can_toggle": request.user.is_superadmin or request.user.is_admin_main,
    })


@login_required
def visits_journal_patient(request, pk):
    """AJAX: детальные даты посещений пациента (кто/когда)."""
    from django.http import JsonResponse
    from .models import PatientVisit
    from django.utils import timezone
    items = [{"id": v.pk, "date": timezone.localtime(v.visited_at).strftime("%d.%m.%Y %H:%M"),
              "doctor": v.doctor.name if v.doctor else "",
              "note": v.note or "", "source": v.get_source_display()}
             for v in PatientVisit.objects.filter(patient_id=pk).select_related("doctor").order_by("-visited_at")]
    return JsonResponse({"items": items})


@login_required
def patient_visits(request, pk):
    """Журнал посещений пациента. Просмотр + добавление/редактирование/удаление (сотрудники клиники)."""
    from .models import PatientVisit
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic
    from django.utils import timezone
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            visited_at = request.POST.get("visited_at") or None
            PatientVisit.objects.create(
                patient=patient,
                visited_at=visited_at or timezone.now(),
                doctor_id=request.POST.get("doctor") or None,
                purpose=(request.POST.get("purpose") or "").strip(),
                note=(request.POST.get("note") or "").strip(),
                source=PatientVisit.SOURCE_MANUAL,
                created_by=request.user,
            )
            messages.success(request, _("Посещение добавлено"))
        elif action == "edit":
            v = PatientVisit.objects.filter(pk=request.POST.get("id"), patient=patient).first()
            if v:
                if request.POST.get("visited_at"):
                    v.visited_at = request.POST.get("visited_at")
                v.doctor_id = request.POST.get("doctor") or None
                v.purpose = (request.POST.get("purpose") or "").strip()
                v.note = (request.POST.get("note") or "").strip()
                v.save(update_fields=["visited_at", "doctor", "purpose", "note", "updated_at"])
                messages.success(request, _("Посещение обновлено"))
        elif action == "delete":
            PatientVisit.objects.filter(pk=request.POST.get("id"), patient=patient).delete()
            messages.success(request, _("Посещение удалено"))
        return redirect("patient_visits", pk=pk)

    visits = list(PatientVisit.objects.filter(patient=patient).select_related("doctor", "appointment"))
    visits_json = {
        str(v.pk): {
            "visited_at": timezone.localtime(v.visited_at).strftime("%Y-%m-%dT%H:%M") if v.visited_at else "",
            "doctor": v.doctor_id or "",
            "purpose": v.purpose or "",
            "note": v.note or "",
        } for v in visits
    }
    return render(request, "patients/visits.html", {
        "patient": patient, "visits": visits, "visits_json": visits_json,
        "doctors": clinic_doctors(get_current_clinic()),
    })


@login_required
def patient_card043_print(request, pk):
    """Печатная «Медицинская карта стоматологического больного» (форма 043/У, КР)."""
    from django.utils import timezone
    from apps.treatments.models_teeth import ToothCondition
    from apps.settings_clinic.models import ClinicSettings
    patient = get_object_or_404(Patient.objects.select_related("primary_doctor", "branch"), pk=pk)
    clinic = ClinicSettings.get()

    # Зубная формула: наш статус → обозначение КР
    KR = {"healthy": "", "caries": "C", "filling": "П", "root_canal": "Pt",
          "crown": "K", "implant": "И", "bridge": "И", "to_remove": "R",
          "missing": "0", "veneer": "П"}
    cond = {tc.tooth_number: KR.get(tc.status.code if tc.status else "", "")
            for tc in ToothCondition.objects.filter(patient=patient).select_related("status")}
    upper = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
    lower = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
    formula_upper = [(n, cond.get(n, "")) for n in upper]
    formula_lower = [(n, cond.get(n, "")) for n in lower]

    # Последняя медкарта — для шапки (диагноз/жалобы/анамнез/осмотр)
    treatments = (Treatment.all_objects.filter(patient=patient, is_deleted=False).exclude(status="cancelled")
                  .select_related("doctor").prefetch_related("emr", "cures__service")
                  .order_by("created_at"))
    last_emr = None
    for t in treatments.order_by("-created_at"):
        if getattr(t, "emr", None):
            last_emr = t.emr
            break

    # Дневник — строки по приёмам
    diary = []
    for t in treatments:
        emr = getattr(t, "emr", None)
        parts = []
        if emr and emr.diagnosis:
            parts.append("Дз: " + emr.diagnosis + (" (%s)" % emr.icd_code if emr.icd_code else ""))
        cures = ", ".join("%s%s" % (c.service.name, (" з.%s" % c.tooth_number if c.tooth_number else "")) for c in t.cures.all())
        if cures:
            parts.append("Лечение: " + cures)
        if emr and emr.recommendations:
            parts.append("Реком.: " + emr.recommendations)
        diary.append({
            "date": timezone.localtime(t.created_at).strftime("%d.%m.%Y"),
            "text": ". ".join(parts) or "—",
            "doctor": t.doctor.name if t.doctor else "",
        })

    return render(request, "patients/card043_print.html", {
        "patient": patient, "clinic": clinic, "today": timezone.localdate(),
        "formula_upper": formula_upper, "formula_lower": formula_lower,
        "emr": last_emr, "diary": diary,
    })


@login_required
def patient_payments_print(request, pk):
    """Печатная история оплат пациента: все платежи с датой, временем и приёмом."""
    from apps.settings_clinic.models import ClinicSettings
    patient = get_object_or_404(Patient, pk=pk)
    payments = Payment.all_clinics.filter(patient=patient).select_related(
        "received_by"
    ).prefetch_related("allocations__treatment__cures__service").order_by("-created_at")
    for p in payments:
        allocs = list(p.allocations.all())
        if allocs:
            p.procedure_label = "; ".join(
                "Приём #{} ({})".format(
                    a.treatment_id,
                    ", ".join(c.service.name for c in a.treatment.cures.all()[:4]) or "без услуг",
                )
                for a in allocs
            )
        else:
            p.procedure_label = "—"
    return render(request, "patients/payments_print.html", {
        "patient": patient, "payments": payments, "clinic_settings": ClinicSettings.get(),
    })


UPPER_TEETH = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
LOWER_TEETH = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]


@login_required
def patient_treatments_print(request, pk):
    """Подробная печать выбранных приёмов: услуги, суммы и зубная схема по каждому."""
    import re
    from apps.settings_clinic.models import ClinicSettings
    patient = get_object_or_404(Patient, pk=pk)
    ids = [int(x) for x in request.GET.get("ids", "").split(",") if x.strip().isdigit()]
    treatments = list(
        Treatment.all_objects.filter(patient=patient, pk__in=ids, is_deleted=False).select_related("doctor", "branch")
        .prefetch_related("cures__service").order_by("created_at")
    )
    for t in treatments:
        marked = set()
        for c in t.cures.all():
            marked.update(int(n) for n in re.findall(r"\d{2}", c.tooth_number or ""))
        t.upper_marks = [(n, n in marked) for n in UPPER_TEETH]
        t.lower_marks = [(n, n in marked) for n in LOWER_TEETH]
    return render(request, "patients/treatments_print.html", {
        "patient": patient, "treatments": treatments, "clinic_settings": ClinicSettings.get(),
    })


@login_required
@require_POST
def patient_tooth_set(request, pk):
    """AJAX: установить/снять статус конкретного зуба пациента."""
    from django.http import JsonResponse
    from apps.treatments.models_teeth import ToothStatus, ToothCondition
    patient = get_object_or_404(Patient, pk=pk)
    try:
        tooth = int(request.POST.get("tooth_number"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "bad tooth"}, status=400)
    status_id = request.POST.get("status_id") or None
    note = request.POST.get("note", "").strip()

    if not status_id:
        # пустой статус → удаляем состояние (зуб «здоров по умолчанию»)
        ToothCondition.objects.filter(patient=patient, tooth_number=tooth).delete()
        return JsonResponse({"ok": True, "tooth": tooth, "cleared": True})

    status = get_object_or_404(ToothStatus, pk=status_id)
    cond, _created = ToothCondition.objects.update_or_create(
        patient=patient, tooth_number=tooth,
        defaults={"status": status, "note": note, "updated_by": request.user},
    )
    return JsonResponse({
        "ok": True, "tooth": tooth,
        "status_id": status.id, "color": status.color, "name": status.name, "note": note,
    })


@login_required
def patient_edit(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    form = PatientForm(request.POST or None, instance=patient)
    if form.is_valid():
        form.save()
        messages.success(request, _("Данные обновлены"))
        return redirect("patient_detail", pk=patient.pk)
    return render(request, "patients/form.html", {"form": form, "title": _("Редактировать пациента"), "object": patient})


@login_required
def patient_delete(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == "POST":
        patient.soft_delete(request.user)   # в корзину, не безвозвратно
        messages.success(request, _("Пациент перемещён в корзину"))
        return redirect("patient_list")
    return render(request, "patients/confirm_delete.html", {"object": patient})
