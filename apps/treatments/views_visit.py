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
from .models_teeth import ToothStatus, ToothCondition, DEFAULT_TOOTH_STATUSES
from .icd10 import DENTAL_ICD10, suggest_icd
from apps.patients.models import Patient


def _ensure_tooth_statuses():
    """Создать дефолтные статусы зубов для текущей клиники, если их нет."""
    if not ToothStatus.objects.exists():
        for i, (code, name, color) in enumerate(DEFAULT_TOOTH_STATUSES):
            ToothStatus.objects.create(code=code, name=name, color=color, sort_order=i)


def _main_branch(request, patient=None):
    from apps.users.models import Branch
    return (Branch.objects.filter(pk=request.session.get("active_branch")).first()
            or Branch.objects.filter(is_main=True).first()
            or (patient.branch if patient else None)
            or Branch.objects.first())


@login_required
def visit_start(request):
    """Начать приём: создать/найти Treatment для записи (или пациента) и открыть мастер."""
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
        messages.error(request, _("Не указан пациент для приёма"))
        return redirect("calendar_view")

    # уже начатый приём по этой записи — продолжаем его, не плодим дубли
    treatment = None
    if appt:
        treatment = (Treatment.objects.filter(appointment=appt)
                     .exclude(status="cancelled").order_by("-created_at").first())
    # Приём уже завершён/оплачен → не запускаем мастер заново, открываем карточку (просмотр)
    if treatment is not None and treatment.status in (Treatment.STATUS_COMPLETED, Treatment.STATUS_PAID):
        return redirect("treatment_detail", pk=treatment.pk)
    # Запись уже завершена, но приёма нет → не создаём новый «пустой» приём
    if appt is not None and appt.status == "completed" and treatment is None:
        messages.info(request, _("Запись уже завершена. Новый приём не создаётся."))
        return redirect("patient_detail", pk=patient.pk)
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
    return redirect("visit_wizard", pk=treatment.pk)


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
    emr, _c = MedicalRecord.objects.get_or_create(
        treatment=treatment,
        defaults={"patient": treatment.patient, "doctor": treatment.doctor},
    )
    _ensure_tooth_statuses()
    from apps.services.models import Service
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic

    services = [{"id": s.pk, "name": s.name, "price": float(s.price),
                 "cat": s.category.name if s.category else ""}
                for s in Service.objects.filter(is_active=True).select_related("category")
                .order_by("category__sort_order", "name")]
    statuses = [{"code": s.code, "name": s.name, "color": s.color} for s in ToothStatus.objects.all()]
    # сохранённые состояния зубов пациента (для предзаполнения карты)
    tooth_conditions = {str(tc.tooth_number): (tc.status.code if tc.status else "")
                        for tc in ToothCondition.objects.filter(patient=treatment.patient).select_related("status")}
    # уже добавленные сегодня процедуры
    cures = [{"service_id": c.service_id, "name": c.service.name, "tooth": c.tooth_number,
              "qty": c.quantity, "price": float(c.price), "done": True}
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
        "objective": emr.objective or "",
        "diagnosis": emr.diagnosis or "",
        "icd_code": emr.icd_code or "",
        "recommendations": emr.recommendations or "",
        "exam_data": emr.exam_data or {},
    }
    return render(request, "treatments/visit.html", {
        "treatment": treatment,
        "patient": treatment.patient,
        "emr": emr,
        "emr_json": emr_json,
        "exam_data": emr.exam_data or {},
        "services_json": services,
        "tooth_statuses_json": statuses,
        "tooth_conditions_json": tooth_conditions,
        "cures_json": cures,
        "files_json": files,
        "file_kinds_json": [{"code": k, "label": lbl} for k, lbl in TreatmentFile.KIND_CHOICES],
        "icd_list_json": [{"code": c, "name": n} for c, n in DENTAL_ICD10],
        "doctors": clinic_doctors(get_current_clinic()),
    })


@login_required
@require_POST
def visit_save(request, pk):
    """Автосохранение шагов (жалобы/осмотр/диагноз + состояния зубов). AJAX."""
    treatment = get_object_or_404(Treatment, pk=pk)
    emr, _c = MedicalRecord.objects.get_or_create(
        treatment=treatment,
        defaults={"patient": treatment.patient, "doctor": treatment.doctor},
    )
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad json"}, status=400)

    emr.complaints = data.get("complaints", emr.complaints) or ""
    emr.anamnesis = data.get("anamnesis", emr.anamnesis) or ""
    emr.external_exam = data.get("external_exam", emr.external_exam) or ""
    emr.objective = data.get("objective", emr.objective) or ""
    emr.diagnosis = data.get("diagnosis", emr.diagnosis) or ""
    emr.icd_code = (data.get("icd_code") or suggest_icd(emr.diagnosis) or "")[:20]
    emr.recommendations = data.get("recommendations", emr.recommendations) or ""
    if isinstance(data.get("exam_data"), dict):
        emr.exam_data = data["exam_data"]
    emr.save()

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
    # план/процедуры — сохраняем и при автосохранении (без списания материалов)
    if isinstance(data.get("plan"), list):
        _apply_plan(treatment, data["plan"], request.user, do_writeoff=False)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def visit_file_upload(request, pk):
    """Загрузка фото/рентгена на шаге Осмотр (привязка к зубу). AJAX, до 10 файлов."""
    from .models import TreatmentFile
    treatment = get_object_or_404(Treatment, pk=pk)
    files = request.FILES.getlist("files") or request.FILES.getlist("file")
    if not files:
        return JsonResponse({"error": "Файл не выбран"}, status=400)
    if len(files) > 10:
        return JsonResponse({"error": "Максимум 10 файлов за раз"}, status=400)
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


def _apply_plan(treatment, items, user, do_writeoff=False):
    """Сохранить набор услуг приёма из мастера (идемпотентно).

    Выполнено сегодня (done) → процедуры приёма (TreatmentCure).
    Остальное → один план лечения, привязанный к этому приёму (переиспользуется).
    do_writeoff=True (только при «Завершить») → списать материалы по нормам услуг.
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

    # — Процедуры (выполнено сегодня) — перезаписываем набор —
    already = treatment.cures.exists()
    treatment.cures.all().delete()
    for it in done_items:
        svc = Service.objects.filter(pk=it.get("service_id")).first()
        if not svc:
            continue
        qty = max(1, int(it.get("qty") or 1))
        TreatmentCure.objects.create(
            treatment=treatment, service=svc, tooth_number=str(it.get("tooth") or ""),
            quantity=qty, price=_price(it, svc), doctor=treatment.doctor,
        )
        if do_writeoff and not already:
            _auto_writeoff_materials(svc, qty, treatment.branch, user)
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
                price=_price(it, svc), quantity=max(1, int(it.get("qty") or 1)),
                doctor=treatment.doctor, sort_order=i,
            )
    elif plan is not None:
        # план опустел → убираем авто-план
        plan.delete()


@login_required
@require_POST
def visit_commit(request, pk):
    """Завершить приём: применить план (выполнено сегодня → процедуры приёма,
    остальное → план лечения), сменить статусы, при необходимости — следующий визит."""
    from apps.services.models import Service
    from .models_plan import TreatmentPlan, TreatmentPlanStage, TreatmentPlanItem
    treatment = get_object_or_404(Treatment.objects.select_related("patient", "doctor"), pk=pk)
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad json"}, status=400)

    items = data.get("plan", [])
    # применяем план + списываем материалы (это финальное сохранение)
    _apply_plan(treatment, items, request.user, do_writeoff=True)

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
