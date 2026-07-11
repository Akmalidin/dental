import json
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from .models import Treatment, TreatmentCure, TreatmentFile, TreatmentFollowUp
from .forms import TreatmentForm, TreatmentCureFormSet
from apps.patients.models import Patient


def _get_own_treatment_or_404(pk, queryset=None):
    """Приём по pk — ищем по клинике его ПАЦИЕНТА (all_objects), не по активной клинике
    вызывающего: иначе прямая ссылка на приём со страницы уже открытого пациента могла
    404-иться при расхождении тегов клиники между пациентом и его приёмами. Граница
    доступа — сам пациент должен быть виден вызывающему в его текущей клинике."""
    base = (queryset if queryset is not None else Treatment.all_objects).filter(is_deleted=False)
    treatment = get_object_or_404(base, pk=pk)
    get_object_or_404(Patient, pk=treatment.patient_id)
    return treatment


@login_required
def treatment_list(request):
    qs = Treatment.objects.select_related("patient", "doctor", "branch").order_by("-created_at")
    if request.user.is_doctor:
        qs = qs.filter(doctor=request.user)
    current_status = request.GET.get("status", "")
    if current_status:
        qs = qs.filter(status=current_status)
    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q)
            | Q(patient__phone__icontains=q) | Q(doctor__name__icontains=q)
            | Q(cures__service__name__icontains=q)
        ).distinct()
    # фильтр «только с долгом»
    only_debt = request.GET.get("debt") == "1"
    if only_debt:
        from django.db.models import F
        qs = qs.exclude(status="cancelled").filter(total_amount__gt=F("paid_amount") + F("discount"))
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    statuses = [
        ("", "Все"), ("planned", "Запланированы"), ("in_progress", "В процессе"),
        ("completed", "Завершены"), ("paid", "Оплачены"), ("cancelled", "Отменены"),
    ]
    return render(request, "treatments/list.html", {
        "treatments": qs,
        "statuses": statuses,
        "current_status": current_status,
        "q": q,
        "date_from": date_from,
        "date_to": date_to,
        "only_debt": only_debt,
    })


def _services_json():
    """Return a plain Python list (json_script in the template handles encoding)."""
    from apps.services.models import Service
    return [
        {"id": s["id"], "name": s["name"], "price": float(s["price"]),
         "cat": s["category__name"] or ""}
        for s in Service.objects.filter(is_active=True).select_related("category")
        .order_by("category__sort_order", "name")
        .values("id", "name", "price", "category__name")
    ]


@login_required
def treatment_create(request):
    # Единый путь приёма — через мастер. Если указан пациент/запись, редиректим туда.
    appt_id = request.GET.get("appointment")
    _patient_id = request.GET.get("patient")
    if appt_id or _patient_id:
        params = []
        if appt_id:
            params.append("appointment=%s" % appt_id)
        if _patient_id:
            params.append("patient=%s" % _patient_id)
        if request.GET.get("doctor"):
            params.append("doctor=%s" % request.GET.get("doctor"))
        return redirect("/treatments/visit/start/?" + "&".join(params))
    from apps.users.models import Branch
    patient_id = request.GET.get("patient")
    patient = get_object_or_404(Patient, pk=patient_id) if patient_id else None
    main_branch = (Branch.objects.filter(pk=request.session.get("active_branch")).first()
                   or Branch.objects.filter(is_main=True).first()
                   or (patient.branch if patient else None)
                   or Branch.objects.first())
    # врач по умолчанию: из GET (?doctor=), иначе из записи пациента, иначе текущий
    from apps.appointments.models import Appointment
    default_doctor = request.user
    appt = None
    appt_id = request.GET.get("appointment")
    if appt_id:
        appt = Appointment.objects.filter(pk=appt_id).select_related("service").prefetch_related("services").first()
    gdoc = request.GET.get("doctor")
    if gdoc:
        from apps.users.models import User as StaffUser
        default_doctor = StaffUser.objects.filter(pk=gdoc).first() or request.user
    elif appt and appt.doctor_id:
        default_doctor = appt.doctor
    elif patient:
        last_appt = (Appointment.objects.filter(patient=patient)
                     .exclude(status="cancelled").order_by("-start_at").first())
        if last_appt and last_appt.doctor_id:
            default_doctor = last_appt.doctor
    # услуги из записи для предзаполнения процедур приёма
    prefill_services = []
    if appt:
        svcs = list(appt.services.all()) or ([appt.service] if appt.service else [])
        prefill_services = [{"id": s.pk, "name": s.name, "price": float(s.price)} for s in svcs if s]
    form = TreatmentForm(request.POST or None, initial={
        "patient": patient, "doctor": default_doctor, "branch": main_branch,
    })
    formset = TreatmentCureFormSet(request.POST or None, prefix="cures")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        treatment = form.save(commit=False)
        if not treatment.branch_id:
            treatment.branch = main_branch
        if appt:
            treatment.appointment = appt
        treatment.save()
        cures = formset.save(commit=False)
        for cure in cures:
            cure.treatment = treatment
            if not cure.doctor_id:
                cure.doctor = treatment.doctor
            if not cure.quantity:
                cure.quantity = 1
            cure.save()
        for cure in formset.deleted_objects:
            cure.delete()
        treatment.recalculate_total()
        # запись, из которой начали приём → «Принимается» (оранжевый в календаре).
        # Завершает приём врач отдельной кнопкой «Завершить приём».
        if appt and appt.status not in ("cancelled", "completed", "in_progress"):
            appt.status = "in_progress"
            appt.save(update_fields=["status"])
        messages.success(request, _("Приём создан"))
        return redirect("treatment_detail", pk=treatment.pk)
    from apps.services.models import Service
    services_data = list(Service.objects.filter(is_active=True).select_related("category")
                         .order_by("category__sort_order", "name"))
    return render(request, "treatments/form.html", {
        "form": form, "formset": formset,
        "services_json": _services_json(),
        "services_data": [{"id": s.pk, "name": s.name, "price": float(s.price),
                           "cat": s.category.name if s.category else ""} for s in services_data],
        "patient": patient,
        "prefill_services_json": prefill_services,
    })


@login_required
def treatment_detail(request, pk):
    treatment = _get_own_treatment_or_404(
        pk, Treatment.all_objects.select_related("patient", "doctor", "branch").prefetch_related(
            "cures__service", "cures__doctor", "files", "followups"
        )
    )
    # Collect treated teeth from cures
    treated_teeth = set()
    for cure in treatment.cures.all():
        for t in (cure.tooth_number or "").replace(" ", "").split(","):
            if t.isdigit():
                treated_teeth.add(int(t))
    plans = treatment.patient.treatment_plans.prefetch_related("items__service").order_by("-created_at")
    from .models_emr import MedicalRecord, MedicalRecordTemplate, EMR_SECTIONS
    emr = getattr(treatment, "emr", None)
    emr_field_map = {"treatment": "treatment_text"}  # form key -> model field
    emr_sections = [
        {"key": k, "label": lbl,
         "value": (getattr(emr, emr_field_map.get(k, k)) if emr else "")}
        for k, lbl in EMR_SECTIONS
    ]
    emr_templates = MedicalRecordTemplate.objects.filter(is_active=True)
    from apps.services.models import Service
    from apps.medicines.models import Medicine
    services_json = [{"id": s.pk, "name": s.name, "price": float(s.price)}
                     for s in Service.objects.filter(is_active=True).order_by("name")]
    medicines_json = [{"id": m.pk, "name": m.name, "unit": m.unit}
                      for m in Medicine.objects.filter(is_active=True).order_by("name")]
    from apps.users.models import Branch
    branches = Branch.objects.filter(is_active=True)
    return render(request, "treatments/detail.html", {
        "treatment": treatment,
        "branches": branches,
        "treated_teeth": sorted(treated_teeth),
        "treated_teeth_json": sorted(treated_teeth),
        "plans": plans,
        "status_choices": Treatment.STATUS_CHOICES,
        "emr": emr,
        "emr_sections": emr_sections,
        "emr_templates_json": [
            {"id": t.pk, "name": t.name, **t.as_dict()} for t in emr_templates
        ],
        "services_json": services_json,
        "medicines_json": medicines_json,
        "doctor_id": treatment.doctor_id,
    })


@login_required
@require_POST
def treatment_delete(request, pk):
    treatment = _get_own_treatment_or_404(pk)
    patient_pk = treatment.patient_id
    treatment.soft_delete(request.user)   # в корзину
    messages.success(request, _("Приём перемещён в корзину"))
    return redirect("patient_detail", pk=patient_pk)


@login_required
@require_POST
def treatment_notify_wa(request, pk):
    """Отправить пациенту в WhatsApp состав приёма: услуги, сумма, оплачено, долг."""
    treatment = _get_own_treatment_or_404(pk, Treatment.all_objects.select_related("patient"))
    patient = treatment.patient
    from apps.notifications.whatsapp import wa_send_text, wa_enabled
    from apps.notifications.models import WaMessage
    from apps.settings_clinic.models import ClinicSettings
    if not patient or not patient.phone:
        messages.error(request, _("У пациента нет телефона"))
        return redirect("patient_detail", pk=patient.pk if patient else None)
    if not wa_enabled():
        messages.error(request, _("WhatsApp не настроен"))
        return redirect("patient_detail", pk=patient.pk)

    cs = ClinicSettings.get()
    clinic_name = (cs.name if cs and cs.name else "Клиника")
    lines = [f"*{clinic_name}*", f"Здравствуйте, {patient.first_name}!",
             f"Приём №{treatment.pk} от {treatment.created_at:%d.%m.%Y}:"]
    for c in treatment.cures.select_related("service").all():
        lines.append(f"• {c.service.name} x{c.quantity} — {c.subtotal:.0f} сом")
    lines.append(f"Итого: {treatment.display_total:.0f} сом")
    if treatment.discount:
        lines.append(f"Скидка: {treatment.discount:.0f} сом")
    lines.append(f"Оплачено: {treatment.paid_amount:.0f} сом")
    if treatment.debt > 0:
        lines.append(f"Долг: {treatment.debt:.0f} сом")
    else:
        lines.append("Оплачено полностью. Спасибо!")
    text = "\n".join(lines)

    ok = wa_send_text(patient.phone, text)
    WaMessage.objects.create(patient=patient, direction="out", phone=patient.phone,
                             body=text, sent_by=request.user, ok=ok)
    if ok:
        messages.success(request, _("Сообщение по приёму отправлено в WhatsApp"))
    else:
        messages.error(request, _("Не удалось отправить (проверьте номер/инстанс WhatsApp)"))
    return redirect("patient_detail", pk=patient.pk)


@login_required
def treatment_edit(request, pk):
    treatment = _get_own_treatment_or_404(pk)
    form = TreatmentForm(request.POST or None, instance=treatment)
    formset = TreatmentCureFormSet(request.POST or None, instance=treatment, prefix="cures")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        treatment = form.save()
        cures = formset.save(commit=False)
        for cure in cures:
            if not cure.doctor_id:
                cure.doctor = treatment.doctor
            if not cure.quantity:
                cure.quantity = 1
            cure.save()
        for cure in formset.deleted_objects:
            cure.delete()
        treatment.recalculate_total()
        messages.success(request, _("Приём обновлён"))
        return redirect("treatment_detail", pk=treatment.pk)
    from apps.services.models import Service as SvcModel
    svc_qs = SvcModel.objects.filter(is_active=True).select_related("category").order_by("category__sort_order","name")
    return render(request, "treatments/form.html", {
        "form": form, "formset": formset, "object": treatment,
        "services_json": _services_json(),
        "services_data": [{"id": s.pk, "name": s.name, "price": float(s.price),
                           "cat": s.category.name if s.category else ""} for s in svc_qs],
    })


def _auto_writeoff_materials(service, qty, branch, user):
    """Automatically write off warehouse materials based on service norms."""
    try:
        from apps.warehouse.models import WarehouseDistribution
        from datetime import date
        norms = service.material_norms.select_related("product").all()
        for norm in norms:
            WarehouseDistribution.objects.create(
                product=norm.product,
                quantity=norm.quantity * qty,
                branch=branch,
                issued_to=user,
                date=date.today(),
                notes=f"Автосписание: {service.name}",
            )
    except Exception:
        # Auto-writeoff is best-effort; never block treatment creation
        pass


@login_required
@require_POST
def treatment_create_quick(request):
    """AJAX endpoint: create Treatment + TreatmentCures from patient detail page."""
    from apps.services.models import Service
    from apps.users.models import Branch
    try:
        data = json.loads(request.body)
        patient_id = data.get("patient_id")
        doctor_id = data.get("doctor_id")
        branch_id = data.get("branch_id")
        cures_data = data.get("cures", [])

        patient = Patient.objects.get(pk=patient_id)
        # Изоляция клиник: врач — только из текущей клиники, иначе текущий пользователь.
        from apps.users.models import clinic_doctors
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        doctor = None
        if doctor_id:
            doctor = clinic_doctors(clinic).filter(pk=doctor_id).first()
        doctor = doctor or request.user

        branch = None
        if branch_id:
            branch = Branch.objects.filter(pk=branch_id, clinic=clinic).first() if clinic else Branch.objects.filter(pk=branch_id).first()
        if not branch:
            branch = request.user.branches.first() or Branch.objects.first()
        if not branch:
            return JsonResponse({"error": "Нет доступных филиалов"}, status=400)

        treatment = Treatment.objects.create(
            patient=patient,
            doctor=doctor,
            branch=branch,
            status=Treatment.STATUS_IN_PROGRESS,
        )
        for c in cures_data:
            service = Service.objects.get(pk=c["service_id"])
            qty = max(1, int(c.get("qty", 1)))
            TreatmentCure.objects.create(
                treatment=treatment,
                service=service,
                tooth_number=c.get("tooth", ""),
                quantity=qty,
                price=service.price,
                doctor=doctor,
            )
            _auto_writeoff_materials(service, qty, branch, request.user)
        treatment.recalculate_total()
        return JsonResponse({"ok": True, "treatment_id": treatment.pk})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def plan_create(request):
    """AJAX: create a treatment plan with items from patient detail."""
    from .models_plan import TreatmentPlan, TreatmentPlanItem, TreatmentPlanStage
    from apps.services.models import Service
    try:
        data = json.loads(request.body)
        patient = Patient.objects.get(pk=data["patient_id"])
        # Изоляция клиник: врач — только из текущей клиники.
        from apps.users.models import clinic_doctors
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        doctor = None
        if data.get("doctor_id"):
            doctor = clinic_doctors(clinic).filter(pk=data["doctor_id"]).first()
        doctor = doctor or request.user
        plan = TreatmentPlan.objects.create(
            patient=patient,
            doctor=doctor,
            title=data.get("title") or "План лечения",
            status=TreatmentPlan.STATUS_DRAFT,
        )
        items = data.get("items", [])
        # услуги кладём в первый этап, чтобы они отображались в редакторе плана
        stage = TreatmentPlanStage.objects.create(plan=plan, title="Этап 1", sort_order=0) if items else None
        for i, it in enumerate(items):
            service = Service.objects.get(pk=it["service_id"])
            TreatmentPlanItem.objects.create(
                plan=plan,
                stage=stage,
                service=service,
                tooth_number=it.get("tooth", ""),
                price=service.price,
                quantity=max(1, int(it.get("qty", 1))),
                doctor=doctor,
                sort_order=i,
            )
        # назначения лекарств (опционально)
        meds = data.get("medicines", [])
        if meds:
            from apps.medicines.models import Medicine, PatientMedicine
            from datetime import date as _date
            treatment_id = data.get("treatment_id")
            for m in meds:
                if not m.get("medicine_id"):
                    continue
                medicine = Medicine.objects.filter(pk=m["medicine_id"]).first()
                if not medicine:
                    continue
                PatientMedicine.objects.create(
                    patient=patient, treatment_id=treatment_id, medicine=medicine,
                    dosage=m.get("dosage", ""), duration=m.get("duration", ""),
                    doctor=doctor, date=_date.today(), notes=m.get("notes", ""),
                )
        return JsonResponse({"ok": True, "plan_id": plan.pk})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def plan_item_toggle(request, pk):
    """Toggle a plan item status (pending <-> done).
    При отметке «выполнено» можно привязать пункт к конкретному приёму (treatment_id)."""
    from .models_plan import TreatmentPlanItem
    item = get_object_or_404(TreatmentPlanItem, pk=pk)
    now_done = item.status != TreatmentPlanItem.STATUS_DONE
    item.status = TreatmentPlanItem.STATUS_DONE if now_done else TreatmentPlanItem.STATUS_PENDING
    fields = ["status"]
    if now_done:
        tid = request.POST.get("treatment_id")
        if tid and Treatment.objects.filter(pk=tid, patient=item.plan.patient).exists():
            item.treatment_id = int(tid)
            fields.append("treatment")
    else:
        item.treatment = None
        fields.append("treatment")
    item.save(update_fields=fields)
    tname = ("приём #%s" % item.treatment_id) if item.treatment_id else ""
    return JsonResponse({"ok": True, "status": item.status,
                         "treatment_id": item.treatment_id, "treatment_label": tname,
                         "completion": item.plan.completion_pct})


@login_required
def plan_detail(request, pk):
    """Full treatment-plan editor page with stages."""
    from .models_plan import TreatmentPlan, TreatmentPlanStage
    plan = get_object_or_404(TreatmentPlan.objects.select_related("patient", "doctor"), pk=pk)
    # самоисцеление: услуги без этапа (старые планы) — привязать к этапу
    orphans = plan.items.filter(stage__isnull=True)
    if orphans.exists():
        n = plan.stages.count()
        stage = TreatmentPlanStage.objects.create(plan=plan, title=f"Этап {n+1}", sort_order=n)
        orphans.update(stage=stage)
    plan = (TreatmentPlan.objects.select_related("patient", "doctor")
            .prefetch_related("stages__items__service", "stages__items__doctor").get(pk=pk))
    from apps.services.models import Service
    services = list(Service.objects.filter(is_active=True).select_related("category")
                    .order_by("category__sort_order", "name")
                    .values("id", "name", "price", "category__name"))
    from apps.users.models import clinic_doctors
    from apps.tenancy import get_current_clinic
    doctors = clinic_doctors(get_current_clinic())
    patient_treatments = (Treatment.all_objects.filter(patient=plan.patient, is_deleted=False)
                          .exclude(status="cancelled").order_by("-created_at")[:50])
    return render(request, "treatments/plan_detail.html", {
        "plan": plan,
        "services_json": [{"id": s["id"], "name": s["name"], "price": float(s["price"]),
                           "cat": s["category__name"] or ""} for s in services],
        "doctors": doctors,
        "patient_treatments": patient_treatments,
    })


@login_required
@require_POST
def plan_stage_add(request, pk):
    from .models_plan import TreatmentPlan, TreatmentPlanStage
    plan = get_object_or_404(TreatmentPlan, pk=pk)
    n = plan.stages.count()
    TreatmentPlanStage.objects.create(plan=plan, title=f"Этап {n+1}", sort_order=n)
    return redirect("plan_detail", pk=pk)


@login_required
@require_POST
def plan_stage_edit(request, pk):
    """Изменить этап плана: название, продолжительность, привязанный визит (приём)."""
    from .models_plan import TreatmentPlanStage
    stage = get_object_or_404(TreatmentPlanStage, pk=pk)
    title = (request.POST.get("title") or "").strip()
    if title:
        stage.title = title
    dur = (request.POST.get("duration_min") or "").strip()
    stage.duration_min = int(dur) if dur.isdigit() and int(dur) > 0 else None
    visit_id = (request.POST.get("visit") or "").strip()
    stage.visit_id = int(visit_id) if visit_id.isdigit() else None
    stage.save(update_fields=["title", "duration_min", "visit"])
    messages.success(request, _("Этап обновлён"))
    return redirect("plan_detail", pk=stage.plan_id)


@login_required
@require_POST
def plan_stage_delete(request, pk):
    from .models_plan import TreatmentPlanStage
    stage = get_object_or_404(TreatmentPlanStage, pk=pk)
    plan_pk = stage.plan_id
    stage.delete()
    return redirect("plan_detail", pk=plan_pk)


@login_required
@require_POST
def plan_item_add(request):
    """AJAX: add a service item to a stage."""
    from .models_plan import TreatmentPlanStage, TreatmentPlanItem
    from apps.services.models import Service
    try:
        data = json.loads(request.body)
        stage = TreatmentPlanStage.objects.get(pk=data["stage_id"])
        service = Service.objects.get(pk=data["service_id"])
        TreatmentPlanItem.objects.create(
            plan=stage.plan, stage=stage, service=service,
            tooth_number=data.get("tooth", ""),
            price=data.get("price") or service.price,
            discount=data.get("discount") or 0,
            quantity=max(1, int(data.get("qty", 1))),
            doctor=stage.plan.doctor,
            sort_order=stage.items.count(),
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def plan_item_delete(request, pk):
    from .models_plan import TreatmentPlanItem
    item = get_object_or_404(TreatmentPlanItem, pk=pk)
    plan_pk = item.plan_id
    item.delete()
    return redirect("plan_detail", pk=plan_pk)


@login_required
@require_POST
def plan_item_move(request, pk):
    """Move or duplicate an item to another stage."""
    from .models_plan import TreatmentPlanItem, TreatmentPlanStage
    item = get_object_or_404(TreatmentPlanItem, pk=pk)
    target_stage_id = request.POST.get("stage_id")
    mode = request.POST.get("mode", "move")  # move | copy
    target = TreatmentPlanStage.objects.filter(pk=target_stage_id, plan=item.plan).first()
    if target:
        if mode == "copy":
            TreatmentPlanItem.objects.create(
                plan=item.plan, stage=target, service=item.service,
                tooth_number=item.tooth_number, price=item.price,
                discount=item.discount, quantity=item.quantity,
                doctor=item.doctor, sort_order=target.items.count(),
            )
        else:
            item.stage = target
            item.save(update_fields=["stage"])
    return redirect("plan_detail", pk=item.plan_id)


@login_required
def plan_print(request, pk):
    """Printable treatment plan (HTML)."""
    from .models_plan import TreatmentPlan
    from apps.settings_clinic.models import ClinicSettings
    plan = get_object_or_404(
        TreatmentPlan.objects.select_related("patient", "doctor").prefetch_related("stages__items__service"),
        pk=pk,
    )
    from django.utils.html import escape
    clinic = ClinicSettings.get()
    rows = ""
    for si, stage in enumerate(plan.stages.all(), 1):
        rows += f'<tr style="background:#f3f3f3"><td colspan="6"><b>Этап {si}: {escape(stage.title)}</b></td></tr>'
        for it in stage.items.all():
            rows += (f"<tr><td>{escape(it.service.name)}</td><td>{escape(it.tooth_number) or '—'}</td>"
                     f"<td>{it.quantity}</td><td>{it.price:.0f}</td><td>{it.discount:.0f}%</td>"
                     f"<td>{it.subtotal:.0f} сом</td></tr>")
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>План лечения</title>
    <style>body{{font-family:Arial,sans-serif;max-width:800px;margin:30px auto;padding:0 30px;color:#1a1a1a}}
    h1{{font-size:20px;text-align:center}} .hdr{{text-align:center;border-bottom:2px solid #333;padding-bottom:10px;margin-bottom:20px}}
    table{{width:100%;border-collapse:collapse;margin-top:10px}} th,td{{border:1px solid #ccc;padding:7px;text-align:left;font-size:14px}}
    th{{background:#f0f0f0}} .total{{text-align:right;font-weight:bold;font-size:16px;margin-top:14px}}
    @media print{{.no-print{{display:none}}}}</style></head><body>
    <div class="hdr"><h1>{escape(clinic.name)}</h1><p>{escape(clinic.address)} · {escape(clinic.phone)}</p></div>
    <h2>План лечения: {escape(plan.title)}</h2>
    <p>Пациент: <b>{escape(plan.patient.full_name)}</b> · Врач: {escape(plan.doctor.name)} · Дата: {plan.created_at:%d.%m.%Y}</p>
    <table><thead><tr><th>Услуга</th><th>Зуб</th><th>Кол-во</th><th>Цена</th><th>Скидка</th><th>Итого</th></tr></thead>
    <tbody>{rows}</tbody></table>
    <p class="total">Итого по плану: {plan.total_price:.0f} сом</p>
    <div class="no-print" style="text-align:center;margin-top:30px"><button onclick="window.print()" style="padding:10px 28px;background:#6366F1;color:#fff;border:none;border-radius:8px;cursor:pointer">🖨 Печать</button></div>
    </body></html>"""
    return HttpResponse(html)


@login_required
def plan_delete(request, pk):
    from .models_plan import TreatmentPlan
    plan = get_object_or_404(TreatmentPlan, pk=pk)
    patient_pk = plan.patient_id
    if request.method == "POST":
        plan.delete()
        messages.success(request, _("План удалён"))
    return redirect("patient_detail", pk=patient_pk)


@login_required
@require_POST
def treatment_emr_save(request, pk):
    """Save the EMR (medical record) for a treatment."""
    from .models_emr import MedicalRecord
    treatment = _get_own_treatment_or_404(pk)
    emr, _created = MedicalRecord.objects.get_or_create(
        treatment=treatment,
        defaults={"patient": treatment.patient, "doctor": treatment.doctor},
    )
    emr.patient = treatment.patient
    if not emr.doctor_id:
        emr.doctor = treatment.doctor
    emr.complaints = request.POST.get("complaints", "")
    emr.anamnesis = request.POST.get("anamnesis", "")
    emr.external_exam = request.POST.get("external_exam", "")
    emr.objective = request.POST.get("objective", "")
    emr.diagnosis = request.POST.get("diagnosis", "")
    emr.treatment_text = request.POST.get("treatment", "")
    emr.recommendations = request.POST.get("recommendations", "")
    emr.save()
    messages.success(request, _("Медкарта сохранена"))
    return redirect("treatment_detail", pk=pk)


@login_required
@require_POST
def treatment_file_upload(request, pk):
    """Загрузка файлов/рентген-снимков к приёму (поддержка нескольких файлов)."""
    from .models import TreatmentFile
    treatment = _get_own_treatment_or_404(pk)
    files = request.FILES.getlist("files") or request.FILES.getlist("file")
    kind = request.POST.get("kind", "xray")
    n = 0
    for f in files:
        TreatmentFile.objects.create(
            treatment=treatment, file=f, kind=kind,
            name=request.POST.get("name") or f.name,
            uploaded_by=request.user,
        )
        n += 1
    if n:
        messages.success(request, _("Загружено файлов: %(n)d") % {"n": n})
    else:
        messages.warning(request, _("Файл не выбран"))
    return redirect("treatment_detail", pk=pk)


@login_required
@require_POST
def treatment_file_delete(request, pk, file_pk):
    from .models import TreatmentFile
    TreatmentFile.objects.filter(pk=file_pk, treatment_id=pk).delete()
    messages.success(request, _("Файл удалён"))
    return redirect("treatment_detail", pk=pk)


@login_required
def treatment_emr_print(request, pk):
    """Printable EMR document."""
    from .models_emr import MedicalRecord, EMR_SECTIONS
    from apps.settings_clinic.models import ClinicSettings
    treatment = _get_own_treatment_or_404(pk, Treatment.all_objects.select_related("patient", "doctor"))
    from django.utils.html import escape
    emr = getattr(treatment, "emr", None)
    clinic = ClinicSettings.get()
    fields = {"complaints": "complaints", "anamnesis": "anamnesis", "external_exam": "external_exam",
              "objective": "objective", "diagnosis": "diagnosis", "treatment": "treatment_text",
              "recommendations": "recommendations"}
    body = ""
    for key, label in EMR_SECTIONS:
        val = getattr(emr, fields[key], "") if emr else ""
        if val:
            body += f"<p><b>{escape(label)}:</b> {escape(val)}</p>"
    if not body:
        body = "<p>Медкарта не заполнена.</p>"
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>ЭМК</title>
    <style>body{{font-family:'Times New Roman',serif;max-width:800px;margin:30px auto;padding:0 30px;line-height:1.6}}
    .hdr{{text-align:center;border-bottom:2px solid #333;padding-bottom:10px;margin-bottom:20px}}
    @media print{{.no-print{{display:none}}}}</style></head><body>
    <div class="hdr"><h2>{escape(clinic.name)}</h2><p>{escape(clinic.address)} · {escape(clinic.phone)}</p></div>
    <h3>Медицинская карта</h3>
    <p>Пациент: <b>{escape(treatment.patient.full_name)}</b> · Врач: {escape(treatment.doctor.name)} · {treatment.created_at:%d.%m.%Y}</p>
    <hr>{body}
    <div class="no-print" style="text-align:center;margin-top:30px"><button onclick="window.print()" style="padding:10px 28px;background:#6366F1;color:#fff;border:none;border-radius:8px;cursor:pointer">🖨 Печать</button></div>
    </body></html>"""
    return HttpResponse(html)


@login_required
@require_POST
def treatment_set_discount(request, pk):
    """Установить/изменить скидку на приём."""
    from decimal import Decimal, InvalidOperation
    treatment = _get_own_treatment_or_404(pk)
    try:
        d = Decimal(str(request.POST.get("discount", "0") or "0"))
        if d < 0:
            d = Decimal("0")
        treatment.discount = d
        treatment.save(update_fields=["discount", "updated_at"])
        treatment.recalculate_total()
        if treatment.patient_id:
            treatment.patient.recalc_balance()
        messages.success(request, f"Скидка обновлена: {d:,.0f} сом")
    except (InvalidOperation, Exception):
        messages.error(request, "Неверное значение скидки")
    return redirect("treatment_detail", pk=pk)


@login_required
@require_POST
def treatment_status(request, pk):
    """Change treatment status (AJAX or form)."""
    treatment = _get_own_treatment_or_404(pk)
    new_status = request.POST.get("status")
    valid = dict(Treatment.STATUS_CHOICES)
    if new_status in valid:
        treatment.status = new_status
        treatment.save(update_fields=["status", "updated_at"])
        # отмена/восстановление приёма меняет баланс пациента
        if treatment.patient_id:
            treatment.patient.recalc_balance()
        messages.success(request, _("Статус изменён: %(s)s") % {"s": valid[new_status]})
    return redirect("treatment_detail", pk=pk)


@login_required
def treatment_print(request, pk):
    """Чек приёма: формат определяется настройкой клиники (thermal/a4/both)."""
    treatment = _get_own_treatment_or_404(
        pk, Treatment.all_objects.prefetch_related("cures__service").select_related("patient", "doctor", "branch")
    )
    from apps.settings_clinic.models import ClinicSettings
    from django.shortcuts import redirect as _redirect
    cs = ClinicSettings.get()
    fmt = getattr(cs, "receipt_format", "thermal")
    # Явный override через ?fmt=
    fmt = request.GET.get("fmt", fmt)

    if fmt == "both":
        # Страница выбора формата
        return render(request, "treatments/receipt_choose.html", {
            "treatment": treatment, "clinic_settings": cs,
        })
    if fmt == "thermal":
        base = request.build_absolute_uri(f"/treatments/{pk}/receipt-print/")
        return _redirect(base)

    # a4 — PDF/HTML
    _has_lab = any(c.warranty_until for c in treatment.cures.all())
    html = render_to_string("treatments/receipt.html", {
        "treatment": treatment, "request": request,
        "clinic_settings": cs, "has_lab": _has_lab,
    })
    try:
        from weasyprint import HTML
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="receipt-{treatment.pk}.pdf"'
        return response
    except ImportError:
        return HttpResponse(html, content_type="text/html")


@login_required
def treatment_receipt_html(request, pk):
    """HTML-чек приёма с QR. ?w=80 — термолента 80мм (автопечать), иначе A4."""
    from apps.finance.views import _qr_svg
    from apps.settings_clinic.models import ClinicSettings
    treatment = _get_own_treatment_or_404(
        pk, Treatment.all_objects.prefetch_related("cures__service").select_related("patient", "doctor", "branch")
    )
    public_url = request.build_absolute_uri(f"/t/{treatment.public_token}/")
    return render(request, "treatments/receipt_thermal.html", {
        "treatment": treatment, "clinic_settings": ClinicSettings.get(),
        "has_lab": any(c.warranty_until for c in treatment.cures.all()),
        "w80": request.GET.get("w") == "80",
        "public_url": public_url, "qr_svg": _qr_svg(public_url),
    })


def treatment_public(request, token):
    """Публичная страница приёма по QR (без логина): услуги+цены, пациент, врач, файлы, зубная формула."""
    treatment = get_object_or_404(
        Treatment._base_manager.select_related("patient", "doctor", "branch", "clinic"),
        public_token=token)
    patient = treatment.patient
    cures = list(treatment.cures.select_related("service", "doctor").all())
    files = list(treatment.files.all())
    for f in files:
        try:
            f.abs_url = request.build_absolute_uri(f.file.url)
        except Exception:
            f.abs_url = ""
    from .models_teeth import ToothCondition
    tooth_map = {}
    if patient:
        for tc in ToothCondition.objects.filter(patient=patient).select_related("status"):
            tooth_map[tc.tooth_number] = tc
    upper = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
    lower = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
    _seen = {}
    for tc in tooth_map.values():
        if tc.status:
            _seen[tc.status_id] = {"name": tc.status.name, "color": tc.status.color}
    from apps.settings_clinic.models import ClinicSettings
    return render(request, "finance/receipt_public.html", {
        "payment": None, "treatment": treatment, "patient": patient,
        "cures": cures, "files": files,
        "formula_upper": [(n, tooth_map.get(n)) for n in upper],
        "formula_lower": [(n, tooth_map.get(n)) for n in lower],
        "has_formula": bool(tooth_map), "tooth_legend": list(_seen.values()),
        "clinic": getattr(treatment, "clinic", None), "clinic_settings": ClinicSettings.get(),
        "has_lab": any((c.warranty_until for c in cures)),
    })
