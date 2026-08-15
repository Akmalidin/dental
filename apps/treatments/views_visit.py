"""Мастер приёма (6 шагов): Пациент → Жалобы → Осмотр → Диагноз → План → Итог.

Открывается по кнопке «Начать приём». Опирается на существующие модели:
Treatment (приём), MedicalRecord (ЭМК), ToothCondition (зубы), TreatmentPlan (план).
Без AI — МКБ-10 из встроенного справочника, план врач формирует сам.
"""
import json
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils.translation import gettext_lazy as _

from .models import Treatment, TreatmentCure, TreatmentFile
from .models_emr import MedicalRecord
from .models_teeth import (
    ToothStatus, ToothCondition, DEFAULT_TOOTH_STATUSES, REAL_TO_JS_TOOTH_CODE,
    ToothSurfaceStatus, ToothGumStatus, ToothSurfaceCondition, ToothGumCondition,
    DEFAULT_SURFACE_STATUSES, DEFAULT_GUM_STATUSES,
)
from .icd10 import DENTAL_ICD10, suggest_icd
from apps.patients.models import Patient


def _ensure_tooth_statuses():
    """Создать дефолтные статусы зубов для текущей клиники, если их нет."""
    if not ToothStatus.objects.exists():
        for i, (code, name, color) in enumerate(DEFAULT_TOOTH_STATUSES):
            ToothStatus.objects.create(code=code, name=name, color=color, sort_order=i)
    if not ToothSurfaceStatus.objects.exists():
        for i, (code, name, color) in enumerate(DEFAULT_SURFACE_STATUSES):
            ToothSurfaceStatus.objects.create(code=code, name=name, color=color, sort_order=i)
    if not ToothGumStatus.objects.exists():
        for i, (code, name, color) in enumerate(DEFAULT_GUM_STATUSES):
            ToothGumStatus.objects.create(code=code, name=name, color=color, sort_order=i)


def _main_branch(request, patient=None):
    from apps.users.models import Branch
    return (Branch.objects.filter(pk=request.session.get("active_branch")).first()
            or Branch.objects.filter(is_main=True).first()
            or (patient.branch if patient else None)
            or Branch.objects.first())


def _resolve_or_create_visit(request):
    """Найти/создать Treatment для приёма (по appointment или patient из GET)
    — общая логика для visit_start (старый интерфейс) и newui_visit_start
    (новый интерфейс), чтобы оба вели себя одинаково и не плодили дубли.

    Возвращает (status, payload):
      "no_patient"  → payload=None — не указан пациент.
      "completed"   → payload=Treatment — приём уже завершён/оплачен, мастер не открываем.
      "appt_done"   → payload=Patient — запись уже завершена, приёма нет, не создаём.
      "ok"          → payload=Treatment — можно открывать мастер.
    """
    from apps.appointments.models import Appointment
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic

    appt = None
    appt_id = request.GET.get("appointment")
    if appt_id:
        appt = Appointment.objects.filter(pk=appt_id).select_related("patient", "doctor").first()
    patient = (appt.patient if appt else None)
    if patient is None:
        patient = Patient.objects.filter(pk=request.GET.get("patient")).first()
    if patient is None:
        return "no_patient", None

    # уже начатый приём по этой записи — продолжаем его, не плодим дубли
    treatment = None
    if appt:
        treatment = (Treatment.objects.filter(appointment=appt)
                     .exclude(status="cancelled").order_by("-created_at").first())
    # Приём уже завершён/оплачен → не запускаем мастер заново, открываем карточку (просмотр)
    if treatment is not None and treatment.status in (Treatment.STATUS_COMPLETED, Treatment.STATUS_PAID):
        return "completed", treatment
    # Запись уже завершена, но приёма нет → не создаём новый «пустой» приём
    if appt is not None and appt.status == "completed" and treatment is None:
        return "appt_done", patient
    if treatment is None:
        clinic = get_current_clinic()
        doctor = None
        gdoc = request.GET.get("doctor") or (appt.doctor_id if appt else None)
        if gdoc:
            doctor = clinic_doctors(clinic).filter(pk=gdoc).first()
        doctor = doctor or (appt.doctor if appt and appt.doctor_id else request.user)
        treatment = Treatment.objects.create(
            patient=patient, doctor=doctor, branch=_main_branch(request, patient),
            status=Treatment.STATUS_IN_PROGRESS, appointment=appt,
        )
    MedicalRecord.objects.get_or_create(
        treatment=treatment,
        defaults={"patient": treatment.patient, "doctor": treatment.doctor},
    )
    # запись → «Принимается»
    if appt and appt.status not in ("cancelled", "completed", "in_progress"):
        appt.status = "in_progress"
        appt.save(update_fields=["status"])
    return "ok", treatment


@login_required
def visit_start(request):
    """Начать приём (старый интерфейс): создать/найти Treatment и открыть мастер."""
    status, payload = _resolve_or_create_visit(request)
    if status == "no_patient":
        messages.error(request, _("Не указан пациент для приёма"))
        return redirect("calendar_view")
    if status == "completed":
        return redirect("treatment_detail", pk=payload.pk)
    if status == "appt_done":
        messages.info(request, _("Запись уже завершена. Новый приём не создаётся."))
        return redirect("patient_detail", pk=payload.pk)
    return redirect("visit_wizard", pk=payload.pk)


@login_required
def visit_wizard(request, pk):
    """Страница мастера приёма (6 шагов)."""
    treatment = get_object_or_404(
        Treatment.objects.select_related("patient", "doctor", "branch", "appointment").prefetch_related("cures__service"),
        pk=pk,
    )
    # Приём уже завершён/оплачен (или запись отмечена «Завершён») → мастер не открываем,
    # показываем карточку приёма (просмотр). Правки — через вкладку ЭМК карточки.
    appt_done = treatment.appointment_id and treatment.appointment.status == "completed"
    if treatment.status in (Treatment.STATUS_COMPLETED, Treatment.STATUS_PAID) or appt_done:
        return redirect("treatment_detail", pk=treatment.pk)
    emr, ctx = _visit_wizard_context(treatment)
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic
    return render(request, "treatments/visit.html", {
        "treatment": treatment,
        "patient": treatment.patient,
        "emr": emr,
        "emr_json": ctx["emr"],
        "exam_data": ctx["emr"]["exam_data"],
        "services_json": ctx["services"],
        "technicians_json": ctx["technicians"],
        "tooth_statuses_json": ctx["toothStatuses"],
        "tooth_conditions_json": ctx["toothConditions"],
        "cures_json": ctx["cures"],
        "files_json": ctx["files"],
        "file_kinds_json": ctx["fileKinds"],
        "icd_list_json": ctx["icdList"],
        "doctors": clinic_doctors(get_current_clinic()),
    })


def _visit_wizard_context(treatment):
    """Данные мастера приёма (ЭМК/зубы/процедуры/файлы/справочники) — общая
    выборка для HTML-страницы старого интерфейса (visit_wizard) и JSON для
    новой карточки приёма (apps.users.newui_views.newui_visitcard). Один
    источник данных — чтобы оба интерфейса видели одно и то же и не
    расходились в бизнес-логике."""
    emr, _c = MedicalRecord.objects.get_or_create(
        treatment=treatment,
        defaults={"patient": treatment.patient, "doctor": treatment.doctor},
    )
    _ensure_tooth_statuses()
    from apps.services.models import Service
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic

    services = [{"id": s.pk, "name": s.name, "price": float(s.price),
                 "cat": s.category.name if s.category else "",
                 "is_lab": s.is_lab, "warranty_months": s.warranty_months, "lab_days": s.lab_days}
                for s in Service.objects.filter(is_active=True).select_related("category")
                .order_by("category__sort_order", "name")]
    from apps.technicians.models import Technician
    technicians_json = [{"id": t.pk, "name": t.name, "lead": t.default_lead_days,
                         "spec": t.get_specialization_display()}
                        for t in Technician.objects.filter(is_active=True)]
    statuses = [{"code": s.code, "name": s.name, "color": s.color} for s in ToothStatus.objects.all()]
    # сохранённые состояния зубов пациента (для предзаполнения карты)
    tooth_conditions = {str(tc.tooth_number): (tc.status.code if tc.status else "")
                        for tc in ToothCondition.objects.filter(patient=treatment.patient).select_related("status")}
    # поверхности и дёсны — коды в БД совпадают с JS 1:1 (см. models_teeth.py),
    # поэтому маппинг не нужен, в отличие от toothConditionsJs выше
    surface_conditions = {f"{sc.tooth_number}-{sc.surface_index}": sc.status.code
                          for sc in ToothSurfaceCondition.objects.filter(patient=treatment.patient).select_related("status")
                          if sc.status}
    gum_conditions = {str(gc.tooth_number): gc.status.code
                      for gc in ToothGumCondition.objects.filter(patient=treatment.patient).select_related("status")
                      if gc.status}
    # уже добавленные сегодня процедуры
    cures = [{"service_id": c.service_id, "name": c.service.name, "tooth": c.tooth_number,
              "qty": c.quantity, "price": float(c.price), "discount": float(c.discount), "done": True}
             for c in treatment.cures.all()]
    # уже загруженные снимки/файлы этого приёма
    from django.utils import timezone as _tz
    files = [{"id": f.pk, "url": f.file.url, "name": f.name,
              "tooth": f.tooth_number, "is_image": f.is_image,
              "kind": f.kind, "kind_label": f.get_kind_display(), "comment": f.comment or "",
              "date": _tz.localtime(f.uploaded_at).strftime("%d.%m.%Y %H:%M"),
              "by": f.uploaded_by.name if f.uploaded_by else ""}
             for f in treatment.files.select_related("uploaded_by").all()]

    emr_json = {
        "complaints": emr.complaints or "",
        "anamnesis": emr.anamnesis or "",
        "externalExam": emr.external_exam or "",
        "objective": emr.objective or "",
        "diagnosis": emr.diagnosis or "",
        "icd_code": emr.icd_code or "",
        "recommendations": emr.recommendations or "",
        "treatmentText": emr.treatment_text or "",
        "exam_data": emr.exam_data or {},
    }
    # Предыдущий визит того же пациента (для «Заполнить анамнез из
    # предыдущих визитов») — реальная последняя ЭМК другого приёма, не демо-текст.
    prev_emr = (MedicalRecord.objects.filter(patient=treatment.patient)
                .exclude(treatment=treatment).order_by("-treatment__created_at").first())
    previous_visit = None
    if prev_emr:
        previous_visit = {
            "complaints": prev_emr.complaints or "",
            "anamnesis": prev_emr.anamnesis or "",
            "externalExam": prev_emr.external_exam or "",
            "objective": prev_emr.objective or "",
            "exam_data": prev_emr.exam_data or {},
        }
    appt = treatment.appointment
    # Чек печатается по Payment.pk (apps.finance.views.payment_receipt), не
    # по Treatment — если по приёму уже принята оплата (обычно из кассы),
    # даём кнопку «Печать чека» прямо на карточке приёма; берём самый
    # свежий платёж (частичная оплата в несколько раз — печатаем последний).
    from apps.finance.models import Payment
    latest_payment = Payment.objects.filter(treatment=treatment).order_by("-created_at").first()
    ctx = {
        "treatmentId": treatment.pk,
        "paymentId": latest_payment.pk if latest_payment else None,
        "status": treatment.status,
        "statusLabel": treatment.get_status_display(),
        "patientId": treatment.patient_id,
        "patientName": treatment.patient.full_name,
        "doctorId": treatment.doctor_id,
        "doctorName": treatment.doctor.name if treatment.doctor else "",
        "appointmentId": treatment.appointment_id,
        "appointmentDate": _tz.localtime(appt.start_at).strftime("%Y-%m-%d") if appt else "",
        "appointmentStart": _tz.localtime(appt.start_at).strftime("%H:%M") if appt else "",
        "appointmentEnd": _tz.localtime(appt.end_at).strftime("%H:%M") if appt else "",
        "appointmentDurationMin": int((appt.end_at - appt.start_at).total_seconds() // 60) if appt else None,
        "createdAt": _tz.localtime(treatment.created_at).strftime("%d.%m.%Y %H:%M"),
        "notes": treatment.notes or "",
        "emr": emr_json,
        "previousVisit": previous_visit,
        "services": services,
        "technicians": technicians_json,
        "toothStatuses": statuses,
        "toothConditions": tooth_conditions,
        # Тот же словарь, что и «Зубная карта» на карточке пациента нового
        # интерфейса (apps.users.views._newui_patientcard_detail_data) —
        # {"adult-14": "caries_mid", ...}, чтобы переиспользовать buildOdontogram()
        # без отдельной ветки маппинга под карточку приёма.
        "toothConditionsJs": {
            f"{'baby' if int(num) >= 51 else 'adult'}-{num}": REAL_TO_JS_TOOTH_CODE.get(code, "norma")
            for num, code in tooth_conditions.items() if code
        },
        # Ключи в формате surfaceStates/gumStates из base.html:
        # "adult-14-s2" для поверхности, "adult-14" для дёсен.
        "toothSurfaceConditionsJs": {
            f"{'baby' if int(key.split('-')[0]) >= 51 else 'adult'}-{key.split('-')[0]}-s{key.split('-')[1]}": code
            for key, code in surface_conditions.items()
        },
        "toothGumConditionsJs": {
            f"{'baby' if int(num) >= 51 else 'adult'}-{num}": code
            for num, code in gum_conditions.items()
        },
        "surfaceStatuses": [{"code": s.code, "name": s.name, "color": s.color}
                            for s in ToothSurfaceStatus.objects.filter(is_active=True)],
        "gumStatuses": [{"code": s.code, "name": s.name, "color": s.color}
                        for s in ToothGumStatus.objects.filter(is_active=True)],
        "cures": cures,
        "files": files,
        "fileKinds": [{"code": k, "label": lbl} for k, lbl in TreatmentFile.KIND_CHOICES],
        "icdList": [{"code": c, "name": n} for c, n in DENTAL_ICD10],
        "doctorOptions": [{"id": d.pk, "name": d.name} for d in clinic_doctors(get_current_clinic())],
    }
    return emr, ctx


@login_required
@require_POST
def visit_save(request, pk):
    """Автосохранение шагов (жалобы/осмотр/диагноз + состояния зубов). AJAX.

    Редактирование ЭМК/зубов/плана разрешено и после завершения приёма
    (поправить диагноз, дописать после того как приём уже закрыт — обычная
    клиническая необходимость). Заблокирован только повторный visit_commit
    (там списание материалов и заказы технику — их нельзя запускать дважды)."""
    treatment = get_object_or_404(Treatment, pk=pk)
    emr, _c = MedicalRecord.objects.get_or_create(
        treatment=treatment,
        defaults={"patient": treatment.patient, "doctor": treatment.doctor},
    )
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad json", "error_key": "generic_invalid_json"}, status=400)

    emr.complaints = data.get("complaints", emr.complaints) or ""
    emr.anamnesis = data.get("anamnesis", emr.anamnesis) or ""
    emr.external_exam = data.get("external_exam", emr.external_exam) or ""
    emr.objective = data.get("objective", emr.objective) or ""
    emr.diagnosis = data.get("diagnosis", emr.diagnosis) or ""
    emr.icd_code = (data.get("icd_code") or suggest_icd(emr.diagnosis) or "")[:20]
    emr.recommendations = data.get("recommendations", emr.recommendations) or ""
    emr.treatment_text = data.get("treatment_text", emr.treatment_text) or ""
    if isinstance(data.get("exam_data"), dict):
        emr.exam_data = data["exam_data"]
    emr.save()

    update_fields = []
    if "notes" in data:
        treatment.notes = data.get("notes") or ""
        update_fields.append("notes")
    # str(...).isdigit() — защита от нечисловых значений (напр. если на фронте
    # <select> отрендерился без value и .value вернул текст опции, не id).
    doctor_id = data.get("doctor_id")
    if doctor_id and str(doctor_id).isdigit():
        from apps.users.models import clinic_doctors
        from apps.tenancy import get_current_clinic
        doctor = clinic_doctors(get_current_clinic()).filter(pk=doctor_id).first()
        if doctor:
            treatment.doctor = doctor
            update_fields.append("doctor")
    if update_fields:
        treatment.save(update_fields=update_fields + ["updated_at"])

    # состояния зубов: {"36": "caries", ...} → upsert ToothCondition пациента
    teeth = data.get("teeth")
    if isinstance(teeth, dict):
        for num, code in teeth.items():
            try:
                tnum = int(num)
            except (ValueError, TypeError):
                continue
            status = ToothStatus.objects.filter(code=code).first() if code else None
            ToothCondition.objects.update_or_create(
                patient=treatment.patient, tooth_number=tnum,
                defaults={"status": status},
            )
    # поверхности зубов: {"36-2": "caries_simple", ...} → upsert ToothSurfaceCondition
    surfaces = data.get("surfaces")
    if isinstance(surfaces, dict):
        for key, code in surfaces.items():
            try:
                tnum_s, sidx_s = key.split("-")
                tnum, sidx = int(tnum_s), int(sidx_s)
            except (ValueError, AttributeError):
                continue
            status = ToothSurfaceStatus.objects.filter(code=code).first() if code else None
            ToothSurfaceCondition.objects.update_or_create(
                patient=treatment.patient, tooth_number=tnum, surface_index=sidx,
                defaults={"status": status, "updated_by": request.user},
            )
    # дёсны зубов: {"36": "parodontoz", ...} → upsert ToothGumCondition
    gums = data.get("gums")
    if isinstance(gums, dict):
        for num, code in gums.items():
            try:
                tnum = int(num)
            except (ValueError, TypeError):
                continue
            status = ToothGumStatus.objects.filter(code=code).first() if code else None
            ToothGumCondition.objects.update_or_create(
                patient=treatment.patient, tooth_number=tnum,
                defaults={"status": status, "updated_by": request.user},
            )
    # план/процедуры — сохраняем и при автосохранении (без списания материалов)
    if isinstance(data.get("plan"), list):
        _apply_plan(treatment, data["plan"], request.user, do_writeoff=False)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def visit_file_upload(request, pk):
    """Загрузка фото/рентгена на шаге Осмотр (привязка к зубу). AJAX, до 10 файлов.
    Разрешена и после завершения приёма — см. docstring visit_save."""
    from .models import TreatmentFile
    treatment = get_object_or_404(Treatment, pk=pk)
    files = request.FILES.getlist("files") or request.FILES.getlist("file")
    if not files:
        return JsonResponse({"error": "Файл не выбран", "error_key": "visit_no_file"}, status=400)
    if len(files) > 10:
        return JsonResponse({"error": "Максимум 10 файлов за раз", "error_key": "visit_max_10_files"}, status=400)
    tooth = request.POST.get("tooth_number") or ""
    tooth_num = int(tooth) if str(tooth).isdigit() else None
    valid_kinds = {k for k, _ in TreatmentFile.KIND_CHOICES}
    kind = request.POST.get("kind") or "intraoral"
    if kind not in valid_kinds:
        kind = "intraoral"
    comment = (request.POST.get("comment") or "").strip()
    from django.utils import timezone as _tz
    created = []
    for f in files:
        obj = TreatmentFile.objects.create(
            treatment=treatment, file=f, tooth_number=tooth_num,
            kind=kind, comment=comment, name=f.name, uploaded_by=request.user,
        )
        created.append({"id": obj.pk, "url": obj.file.url, "name": obj.name,
                        "tooth": tooth_num, "is_image": obj.is_image,
                        "kind": obj.kind, "kind_label": obj.get_kind_display(),
                        "comment": obj.comment,
                        "date": _tz.localtime(obj.uploaded_at).strftime("%d.%m.%Y %H:%M"),
                        "by": request.user.name if hasattr(request.user, "name") else ""})
    return JsonResponse({"files": created})


def _apply_plan(treatment, items, user, do_writeoff=False, create_orders=False):
    """Сохранить набор услуг приёма из мастера (идемпотентно).

    Выполнено сегодня (done) → процедуры приёма (TreatmentCure).
    Остальное → один план лечения, привязанный к этому приёму (переиспользуется).
    do_writeoff=True (только при «Завершить») → списать материалы по нормам услуг.
    create_orders=True (при «Завершить») → создать заказы технику по лаб-услугам.
    """
    from apps.services.models import Service
    from .models_plan import TreatmentPlan, TreatmentPlanStage, TreatmentPlanItem
    from .views import _auto_writeoff_materials
    items = items or []
    done_items = [it for it in items if it.get("done")]
    future_items = [it for it in items if not it.get("done")]

    def _price(it, svc):
        v = it.get("price")
        return Decimal(str(v if v not in (None, "") else svc.price))

    def _discount(it):
        try:
            v = Decimal(str(it.get("discount") or 0))
        except Exception:
            return Decimal(0)
        return max(Decimal(0), min(Decimal(100), v))

    # — Процедуры (выполнено сегодня) — перезаписываем набор —
    already = treatment.cures.exists()
    treatment.cures.all().delete()
    for it in done_items:
        svc = Service.objects.filter(pk=it.get("service_id")).first()
        if not svc:
            continue
        qty = max(1, int(it.get("qty") or 1))
        cure = TreatmentCure.objects.create(
            treatment=treatment, service=svc, tooth_number=str(it.get("tooth") or ""),
            quantity=qty, price=_price(it, svc), discount=_discount(it), doctor=treatment.doctor,
        )
        if do_writeoff and not already:
            _auto_writeoff_materials(svc, qty, treatment.branch, user)
        # — Заказ технику по лабораторной услуге —
        if create_orders and svc.is_lab and it.get("technician_id"):
            _create_lab_order(treatment, cure, svc, it, user)
    treatment.recalculate_total()

    # — План на будущее — один план на приём, переиспользуем (без дублей при автосохранении) —
    plan_title = "План по приёму #%s" % treatment.pk
    plan = TreatmentPlan.objects.filter(patient=treatment.patient, title=plan_title).first()
    if future_items:
        if plan is None:
            plan = TreatmentPlan.objects.create(
                patient=treatment.patient, doctor=treatment.doctor,
                title=plan_title, status=TreatmentPlan.STATUS_APPROVED,
            )
        stage = plan.stages.first() or TreatmentPlanStage.objects.create(plan=plan, title="Этап 1", sort_order=0)
        plan.items.all().delete()
        for i, it in enumerate(future_items):
            svc = Service.objects.filter(pk=it.get("service_id")).first()
            if not svc:
                continue
            TreatmentPlanItem.objects.create(
                plan=plan, stage=stage, service=svc, tooth_number=str(it.get("tooth") or ""),
                price=_price(it, svc), discount=_discount(it), quantity=max(1, int(it.get("qty") or 1)),
                doctor=treatment.doctor, sort_order=i,
            )
    elif plan is not None:
        # план опустел → убираем авто-план
        plan.delete()


def _create_lab_order(treatment, cure, svc, it, user):
    """Создать заказ зуботехнику по лабораторной услуге приёма."""
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    from apps.technicians.models import Technician, TechnicianAgreement, TechnicianTask, TechnicianOrderEvent
    tech = Technician.objects.filter(pk=it.get("technician_id")).first()
    if not tech:
        return
    today = _tz.localdate()
    lead = it.get("lead_days")
    try:
        lead = int(lead)
    except (TypeError, ValueError):
        lead = tech.default_lead_days or svc.lab_days or 5
    # себестоимость работы техника: из договора, иначе 0
    agr = TechnicianAgreement.objects.filter(technician=tech, service=svc).first()
    amount = agr.price if agr else Decimal(0)
    order = TechnicianTask.objects.create(
        technician=tech, treatment=treatment, patient=treatment.patient, cure=cure,
        service=svc, tooth_number=str(it.get("tooth") or ""),
        material=(it.get("material") or "").strip(), vita_color=(it.get("vita") or "").strip(),
        amount=amount, doctor_comment=(it.get("tech_comment") or "").strip(),
        status=TechnicianTask.STATUS_TRANSFERRED, transferred_at=today,
        expected_ready=today + _td(days=lead),
    )
    TechnicianOrderEvent.objects.create(task=order, status=order.status, by=user)
    # сразу проставим техника в процедуру (гарантия — при установке)
    cure.technician = tech
    cure.lab_order = order
    cure.save(update_fields=["technician", "lab_order"])


@login_required
@require_POST
def visit_commit(request, pk):
    """Завершить приём: применить план (выполнено сегодня → процедуры приёма,
    остальное → план лечения), сменить статусы, при необходимости — следующий визит."""
    from apps.services.models import Service
    from .models_plan import TreatmentPlan, TreatmentPlanStage, TreatmentPlanItem
    treatment = get_object_or_404(Treatment.objects.select_related("patient", "doctor"), pk=pk)
    if treatment.status in (Treatment.STATUS_COMPLETED, Treatment.STATUS_PAID):
        return JsonResponse({"error": "Приём уже завершён", "error_key": "visit_already_completed"}, status=403)
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad json", "error_key": "generic_invalid_json"}, status=400)

    items = data.get("plan", [])
    # применяем план + списываем материалы + создаём заказы технику (финальное сохранение)
    _apply_plan(treatment, items, request.user, do_writeoff=True, create_orders=True)

    # — Завершить приём и запись —
    treatment.status = Treatment.STATUS_COMPLETED
    treatment.save(update_fields=["status", "updated_at"])
    if treatment.appointment_id:
        from apps.appointments.models import Appointment
        Appointment.objects.filter(pk=treatment.appointment_id).exclude(
            status__in=["cancelled"]).update(status="completed")

    # — Следующий визит (необязательно) —
    nxt = data.get("next_visit") or {}
    created_next = None
    if nxt.get("date") and nxt.get("time"):
        from datetime import datetime, timedelta
        from django.utils import timezone as _tz
        from apps.appointments.models import Appointment
        try:
            start = datetime.strptime("%s %s" % (nxt["date"], nxt["time"]), "%Y-%m-%d %H:%M")
            if _tz.is_naive(start):
                start = _tz.make_aware(start)
            end = start + timedelta(minutes=30)
            created_next = Appointment.objects.create(
                patient=treatment.patient, doctor=treatment.doctor,
                branch=treatment.branch, start_at=start, end_at=end,
                status="scheduled", created_by=request.user,
                notes=nxt.get("note", ""),
            )
        except (ValueError, TypeError):
            created_next = None

    return JsonResponse({
        "ok": True,
        "treatment_id": treatment.pk,
        "redirect": "/treatments/%s/" % treatment.pk,
        "next_visit": created_next.pk if created_next else None,
    })
