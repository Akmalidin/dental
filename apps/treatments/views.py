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


@login_required
def treatment_list(request):
    qs = Treatment.objects.select_related("patient", "doctor", "branch").order_by("-created_at")
    if request.user.is_doctor:
        qs = qs.filter(doctor=request.user)
    current_status = request.GET.get("status", "")
    if current_status:
        qs = qs.filter(status=current_status)
    statuses = [
        ("", "Все"), ("planned", "Запланированы"), ("in_progress", "В процессе"),
        ("completed", "Завершены"), ("paid", "Оплачены"), ("cancelled", "Отменены"),
    ]
    return render(request, "treatments/list.html", {
        "treatments": qs,
        "statuses": statuses,
        "current_status": current_status,
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
    from apps.users.models import Branch
    patient_id = request.GET.get("patient")
    patient = get_object_or_404(Patient, pk=patient_id) if patient_id else None
    main_branch = (Branch.objects.filter(is_main=True).first()
                   or (patient.branch if patient else None)
                   or Branch.objects.first())
    form = TreatmentForm(request.POST or None, initial={
        "patient": patient, "doctor": request.user, "branch": main_branch,
    })
    formset = TreatmentCureFormSet(request.POST or None, prefix="cures")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        treatment = form.save(commit=False)
        if not treatment.branch_id:
            treatment.branch = main_branch
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
    })


@login_required
def treatment_detail(request, pk):
    treatment = get_object_or_404(
        Treatment.objects.select_related("patient", "doctor", "branch").prefetch_related(
            "cures__service", "cures__doctor", "files", "followups"
        ),
        pk=pk,
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
    return render(request, "treatments/detail.html", {
        "treatment": treatment,
        "treated_teeth": sorted(treated_teeth),
        "treated_teeth_json": sorted(treated_teeth),
        "plans": plans,
        "status_choices": Treatment.STATUS_CHOICES,
        "emr": emr,
        "emr_sections": emr_sections,
        "emr_templates_json": [
            {"id": t.pk, "name": t.name, **t.as_dict()} for t in emr_templates
        ],
    })


@login_required
def treatment_edit(request, pk):
    treatment = get_object_or_404(Treatment, pk=pk)
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
        User = request.user.__class__
        doctor = User.objects.get(pk=doctor_id) if doctor_id else request.user

        branch = None
        if branch_id:
            branch = Branch.objects.filter(pk=branch_id).first()
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
    from .models_plan import TreatmentPlan, TreatmentPlanItem
    from apps.services.models import Service
    try:
        data = json.loads(request.body)
        patient = Patient.objects.get(pk=data["patient_id"])
        User = request.user.__class__
        doctor = User.objects.get(pk=data["doctor_id"]) if data.get("doctor_id") else request.user
        plan = TreatmentPlan.objects.create(
            patient=patient,
            doctor=doctor,
            title=data.get("title") or "План лечения",
            status=TreatmentPlan.STATUS_DRAFT,
        )
        for i, it in enumerate(data.get("items", [])):
            service = Service.objects.get(pk=it["service_id"])
            TreatmentPlanItem.objects.create(
                plan=plan,
                service=service,
                tooth_number=it.get("tooth", ""),
                price=service.price,
                quantity=max(1, int(it.get("qty", 1))),
                doctor=doctor,
                sort_order=i,
            )
        return JsonResponse({"ok": True, "plan_id": plan.pk})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def plan_item_toggle(request, pk):
    """Toggle a plan item status (pending <-> done)."""
    from .models_plan import TreatmentPlanItem
    item = get_object_or_404(TreatmentPlanItem, pk=pk)
    item.status = (TreatmentPlanItem.STATUS_PENDING
                   if item.status == TreatmentPlanItem.STATUS_DONE
                   else TreatmentPlanItem.STATUS_DONE)
    item.save(update_fields=["status"])
    return JsonResponse({"ok": True, "status": item.status,
                         "completion": item.plan.completion_pct})


@login_required
def plan_detail(request, pk):
    """Full treatment-plan editor page with stages."""
    from .models_plan import TreatmentPlan
    plan = get_object_or_404(
        TreatmentPlan.objects.select_related("patient", "doctor").prefetch_related(
            "stages__items__service", "stages__items__doctor"
        ), pk=pk,
    )
    from apps.services.models import Service
    services = list(Service.objects.filter(is_active=True).select_related("category")
                    .order_by("category__sort_order", "name")
                    .values("id", "name", "price", "category__name"))
    doctors = request.user.__class__.objects.filter(role__name="doctor", is_active=True)
    return render(request, "treatments/plan_detail.html", {
        "plan": plan,
        "services_json": [{"id": s["id"], "name": s["name"], "price": float(s["price"]),
                           "cat": s["category__name"] or ""} for s in services],
        "doctors": doctors,
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
    clinic = ClinicSettings.get()
    rows = ""
    for si, stage in enumerate(plan.stages.all(), 1):
        rows += f'<tr style="background:#f3f3f3"><td colspan="6"><b>Этап {si}: {stage.title}</b></td></tr>'
        for it in stage.items.all():
            rows += (f"<tr><td>{it.service.name}</td><td>{it.tooth_number or '—'}</td>"
                     f"<td>{it.quantity}</td><td>{it.price:.0f}</td><td>{it.discount:.0f}%</td>"
                     f"<td>{it.subtotal:.0f} сом</td></tr>")
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>План лечения</title>
    <style>body{{font-family:Arial,sans-serif;max-width:800px;margin:30px auto;padding:0 30px;color:#1a1a1a}}
    h1{{font-size:20px;text-align:center}} .hdr{{text-align:center;border-bottom:2px solid #333;padding-bottom:10px;margin-bottom:20px}}
    table{{width:100%;border-collapse:collapse;margin-top:10px}} th,td{{border:1px solid #ccc;padding:7px;text-align:left;font-size:14px}}
    th{{background:#f0f0f0}} .total{{text-align:right;font-weight:bold;font-size:16px;margin-top:14px}}
    @media print{{.no-print{{display:none}}}}</style></head><body>
    <div class="hdr"><h1>{clinic.name}</h1><p>{clinic.address} · {clinic.phone}</p></div>
    <h2>План лечения: {plan.title}</h2>
    <p>Пациент: <b>{plan.patient.full_name}</b> · Врач: {plan.doctor.name} · Дата: {plan.created_at:%d.%m.%Y}</p>
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
    treatment = get_object_or_404(Treatment, pk=pk)
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
def treatment_emr_print(request, pk):
    """Printable EMR document."""
    from .models_emr import MedicalRecord, EMR_SECTIONS
    from apps.settings_clinic.models import ClinicSettings
    treatment = get_object_or_404(Treatment.objects.select_related("patient", "doctor"), pk=pk)
    emr = getattr(treatment, "emr", None)
    clinic = ClinicSettings.get()
    fields = {"complaints": "complaints", "anamnesis": "anamnesis", "external_exam": "external_exam",
              "objective": "objective", "diagnosis": "diagnosis", "treatment": "treatment_text",
              "recommendations": "recommendations"}
    body = ""
    for key, label in EMR_SECTIONS:
        val = getattr(emr, fields[key], "") if emr else ""
        if val:
            body += f"<p><b>{label}:</b> {val}</p>"
    if not body:
        body = "<p>Медкарта не заполнена.</p>"
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>ЭМК</title>
    <style>body{{font-family:'Times New Roman',serif;max-width:800px;margin:30px auto;padding:0 30px;line-height:1.6}}
    .hdr{{text-align:center;border-bottom:2px solid #333;padding-bottom:10px;margin-bottom:20px}}
    @media print{{.no-print{{display:none}}}}</style></head><body>
    <div class="hdr"><h2>{clinic.name}</h2><p>{clinic.address} · {clinic.phone}</p></div>
    <h3>Медицинская карта</h3>
    <p>Пациент: <b>{treatment.patient.full_name}</b> · Врач: {treatment.doctor.name} · {treatment.created_at:%d.%m.%Y}</p>
    <hr>{body}
    <div class="no-print" style="text-align:center;margin-top:30px"><button onclick="window.print()" style="padding:10px 28px;background:#6366F1;color:#fff;border:none;border-radius:8px;cursor:pointer">🖨 Печать</button></div>
    </body></html>"""
    return HttpResponse(html)


@login_required
@require_POST
def treatment_status(request, pk):
    """Change treatment status (AJAX or form)."""
    treatment = get_object_or_404(Treatment, pk=pk)
    new_status = request.POST.get("status")
    valid = dict(Treatment.STATUS_CHOICES)
    if new_status in valid:
        treatment.status = new_status
        treatment.save(update_fields=["status", "updated_at"])
        messages.success(request, _("Статус изменён: %(s)s") % {"s": valid[new_status]})
    return redirect("treatment_detail", pk=pk)


@login_required
def treatment_print(request, pk):
    """PDF receipt for a treatment."""
    treatment = get_object_or_404(
        Treatment.objects.prefetch_related("cures__service").select_related("patient", "doctor", "branch"),
        pk=pk,
    )
    html = render_to_string("treatments/receipt.html", {"treatment": treatment, "request": request})
    try:
        from weasyprint import HTML
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="receipt-{treatment.pk}.pdf"'
        return response
    except ImportError:
        return HttpResponse(html, content_type="text/html")
