from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import ClinicSettings
from .models_documents import DocumentTemplate
from .forms import ClinicSettingsForm
from apps.users.decorators import role_required


@login_required
@role_required("superadmin", "admin_main")
def settings_view(request):
    instance = ClinicSettings.get()
    form = ClinicSettingsForm(request.POST or None, request.FILES or None, instance=instance)
    if form.is_valid():
        form.save()
        messages.success(request, _("Настройки сохранены"))
        return redirect("clinic_settings")
    from apps.users.models import Branch
    return render(request, "settings/settings.html", {
        "form": form,
        "branches": Branch.objects.all(),
        "module_choices": ClinicSettings.ALL_MODULES,
    })


# ─── Справочники (reference dictionaries) ────────────────────────────────────

def _ref_models():
    from apps.warehouse.models import Supplier, ProductCategory
    from apps.services.models import ServiceCategory
    from apps.patients.models import LeadSource
    from apps.patients.models_insurance import InsuranceCompany
    from apps.appointments.models import CancellationReason
    return {
        "suppliers": (Supplier, "Поставщики", "supplier"),
        "product_categories": (ProductCategory, "Категории материалов", "tag"),
        "service_categories": (ServiceCategory, "Категории услуг", "tag"),
        "sources": (LeadSource, "Источники обращений", "globe"),
        "insurance": (InsuranceCompany, "Страховые компании", "shield"),
        "cancel_reasons": (CancellationReason, "Причины отмены записи", "x"),
    }


@login_required
@role_required("superadmin", "admin_main")
def references(request):
    refs = _ref_models()
    data = []
    for key, (Model, label, icon) in refs.items():
        data.append({"key": key, "label": label, "icon": icon, "items": Model.objects.all()})
    return render(request, "settings/references.html", {"refs": data})


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def reference_add(request, kind):
    refs = _ref_models()
    if kind in refs:
        Model = refs[kind][0]
        name = request.POST.get("name", "").strip()
        if name:
            # Supplier requires a phone field; default empty handled by model
            kwargs = {"name": name}
            try:
                Model.objects.create(**kwargs)
            except Exception:
                # models with extra required fields (Supplier.phone) — set blank
                Model.objects.create(name=name, phone="")
            messages.success(request, _("Добавлено: %(n)s") % {"n": name})
    return redirect("references")


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def reference_delete(request, kind, pk):
    refs = _ref_models()
    if kind in refs:
        refs[kind][0].objects.filter(pk=pk).delete()
        messages.success(request, _("Удалено"))
    return redirect("references")


# ─── ЭМК шаблоны (medical record templates) ──────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def emr_template_list(request):
    from apps.treatments.models_emr import MedicalRecordTemplate
    q = request.GET.get("q", "")
    templates = MedicalRecordTemplate.objects.all()
    if q:
        templates = templates.filter(name__icontains=q)
    return render(request, "settings/emr_templates.html", {"templates": templates, "q": q})


@login_required
@role_required("superadmin", "admin_main")
def emr_template_edit(request, pk=None):
    from apps.treatments.models_emr import MedicalRecordTemplate, EMR_SECTIONS
    tpl = get_object_or_404(MedicalRecordTemplate, pk=pk) if pk else None
    if request.method == "POST":
        if tpl is None:
            tpl = MedicalRecordTemplate()
        tpl.name = request.POST.get("name", "").strip() or "Без названия"
        for key, _label in EMR_SECTIONS:
            setattr(tpl, key, request.POST.get(key, ""))
        tpl.is_active = bool(request.POST.get("is_active", True))
        tpl.save()
        messages.success(request, _("Шаблон ЭМК сохранён"))
        return redirect("emr_template_list")
    sections = [{"key": k, "label": lbl, "value": (getattr(tpl, k) if tpl else "")} for k, lbl in EMR_SECTIONS]
    return render(request, "settings/emr_template_form.html", {"object": tpl, "sections": sections})


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def emr_template_delete(request, pk):
    from apps.treatments.models_emr import MedicalRecordTemplate
    MedicalRecordTemplate.objects.filter(pk=pk).delete()
    messages.success(request, _("Шаблон удалён"))
    return redirect("emr_template_list")


# ─── Статусы зубов (tooth statuses) ──────────────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def tooth_status_list(request):
    from apps.treatments.models_teeth import ToothStatus
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        color = request.POST.get("color", "").strip() or "#6366F1"
        if name:
            ToothStatus.objects.create(
                name=name, color=color,
                sort_order=ToothStatus.objects.count(),
            )
            messages.success(request, _("Статус добавлен"))
        return redirect("tooth_status_list")
    statuses = ToothStatus.objects.all()
    return render(request, "settings/tooth_statuses.html", {"statuses": statuses})


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def tooth_status_edit(request, pk):
    from apps.treatments.models_teeth import ToothStatus
    s = get_object_or_404(ToothStatus, pk=pk)
    s.name = request.POST.get("name", s.name).strip() or s.name
    s.color = request.POST.get("color", s.color).strip() or s.color
    s.is_active = bool(request.POST.get("is_active"))
    s.save()
    messages.success(request, _("Статус обновлён"))
    return redirect("tooth_status_list")


@login_required
@role_required("superadmin", "admin_main")
@require_POST
def tooth_status_delete(request, pk):
    from apps.treatments.models_teeth import ToothStatus
    ToothStatus.objects.filter(pk=pk).delete()
    messages.success(request, _("Статус удалён"))
    return redirect("tooth_status_list")


# ─── Document templates ──────────────────────────────────────────────────────

@login_required
@role_required("superadmin", "admin_main")
def document_list(request):
    templates = DocumentTemplate.objects.all()
    return render(request, "settings/documents.html", {"templates": templates})


@login_required
@role_required("superadmin", "admin_main")
def document_create(request):
    if request.method == "POST":
        DocumentTemplate.objects.create(
            name=request.POST.get("name", "").strip() or "Без названия",
            doc_type=request.POST.get("doc_type", "consent"),
            content=request.POST.get("content", ""),
            is_active=bool(request.POST.get("is_active")),
        )
        messages.success(request, _("Шаблон создан"))
        return redirect("document_list")
    return render(request, "settings/document_form.html", {
        "doc_types": DocumentTemplate.TYPE_CHOICES,
    })


@login_required
@role_required("superadmin", "admin_main")
def document_edit(request, pk):
    tpl = get_object_or_404(DocumentTemplate, pk=pk)
    if request.method == "POST":
        tpl.name = request.POST.get("name", "").strip() or tpl.name
        tpl.doc_type = request.POST.get("doc_type", tpl.doc_type)
        tpl.content = request.POST.get("content", "")
        tpl.is_active = bool(request.POST.get("is_active"))
        tpl.save()
        messages.success(request, _("Шаблон обновлён"))
        return redirect("document_list")
    return render(request, "settings/document_form.html", {
        "object": tpl,
        "doc_types": DocumentTemplate.TYPE_CHOICES,
    })


@login_required
@role_required("superadmin", "admin_main")
def document_delete(request, pk):
    tpl = get_object_or_404(DocumentTemplate, pk=pk)
    if request.method == "POST":
        tpl.delete()
        messages.success(request, _("Шаблон удалён"))
    return redirect("document_list")


@login_required
def document_render(request, pk, patient_pk):
    """Render a document template for a patient and return printable HTML."""
    from apps.patients.models import Patient
    tpl = get_object_or_404(DocumentTemplate, pk=pk)
    patient = get_object_or_404(Patient, pk=patient_pk)
    clinic = ClinicSettings.get()

    # Build last treatment services / teeth
    last_treatment = patient.treatments.prefetch_related("cures__service").order_by("-created_at").first()
    services_str = ""
    teeth_str = ""
    if last_treatment:
        cures = list(last_treatment.cures.all())
        services_str = ", ".join(c.service.name for c in cures)
        teeth_str = ", ".join(c.tooth_number for c in cures if c.tooth_number)

    context = {
        "patient_name": patient.full_name,
        "patient_dob": patient.birth_date.strftime("%d.%m.%Y") if patient.birth_date else "",
        "patient_phone": patient.phone,
        "patient_address": patient.address,
        "doctor_name": (patient.primary_doctor.name if patient.primary_doctor else (request.user.name)),
        "clinic_name": clinic.name,
        "clinic_phone": clinic.phone,
        "clinic_address": clinic.address,
        "date": timezone.now().strftime("%d.%m.%Y"),
        "services": services_str,
        "tooth_numbers": teeth_str,
    }
    body = tpl.render(context)
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
    <title>{tpl.name}</title>
    <style>
      body {{ font-family: 'Times New Roman', serif; max-width: 800px; margin: 40px auto; padding: 0 40px; line-height: 1.6; color: #1a1a1a; }}
      .doc-header {{ text-align: center; border-bottom: 2px solid #333; padding-bottom: 12px; margin-bottom: 24px; }}
      .doc-header h1 {{ font-size: 20px; margin: 0; }}
      .doc-header p {{ margin: 4px 0 0; font-size: 13px; color: #555; }}
      .doc-body {{ white-space: pre-wrap; font-size: 15px; }}
      .doc-sign {{ margin-top: 60px; display: flex; justify-content: space-between; font-size: 14px; }}
      @media print {{ body {{ margin: 0; }} .no-print {{ display: none; }} }}
    </style></head><body>
    <div class="doc-header"><h1>{clinic.name}</h1><p>{clinic.address} · {clinic.phone}</p></div>
    <div class="doc-body">{body}</div>
    <div class="doc-sign">
      <div>Пациент: _________________ / {patient.full_name}</div>
      <div>Дата: {context['date']}</div>
    </div>
    <div class="no-print" style="text-align:center;margin-top:40px">
      <button onclick="window.print()" style="padding:10px 28px;background:#6366F1;color:#fff;border:none;border-radius:8px;font-size:14px;cursor:pointer">🖨 Печать</button>
    </div>
    </body></html>"""
    return HttpResponse(html)
