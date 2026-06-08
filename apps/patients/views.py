from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from django.views.decorators.http import require_POST

from .models import Patient, Tag, LeadSource
from .forms import PatientForm
from apps.treatments.models import Treatment
from apps.finance.models import Payment


@login_required
def patient_list(request):
    from datetime import date, timedelta
    from django.db.models import Sum
    from decimal import Decimal

    qs = Patient.objects.select_related("branch", "source").prefetch_related("tags")
    q = request.GET.get("q", "")
    branch_id = request.GET.get("branch", "")
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(middle_name__icontains=q)
            | Q(phone__icontains=q)
        )
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    today = date.today()
    week_ago = today - timedelta(days=7)

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

    debtors = Patient.objects.filter(balance__lt=0)
    debtors_count = debtors.count()
    debtors_total = debtors.aggregate(s=Sum("balance"))["s"] or Decimal(0)

    from apps.users.models import Branch
    branches = Branch.objects.all()

    return render(request, "patients/list.html", {
        "patients": qs,
        "q": q,
        "sources": LeadSource.objects.filter(is_active=True),
        "branches": branches,
        "all_count": all_count,
        "new_count": new_count,
        "birthday_count": birthday_count,
        "debtors_count": debtors_count,
        "debtors_total": abs(debtors_total),
    })


@login_required
def patient_create(request):
    form = PatientForm(request.POST or None)
    if form.is_valid():
        patient = form.save(commit=False)
        patient.created_by = request.user
        patient.save()
        form.save_m2m()
        messages.success(request, _("Пациент добавлен"))
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
    treatments = Treatment.objects.filter(patient=patient).select_related(
        "doctor", "branch"
    ).prefetch_related(
        "cures__service", "cures__doctor", "files"
    ).annotate(_status_order=status_order).order_by("_status_order", "-created_at")
    payments = Payment.objects.filter(patient=patient).select_related("received_by").order_by("-created_at")
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
    """Отдельная страница: отправить пациенту WhatsApp-сообщение."""
    patient = get_object_or_404(Patient, pk=pk)
    from apps.notifications.whatsapp import wa_send_text, wa_enabled, render_message
    from apps.notifications.models import MessageTemplate, WaMessage

    if request.method == "POST":
        text = (request.POST.get("text") or "").strip()
        if not text:
            messages.error(request, _("Введите текст сообщения"))
        elif not patient.phone:
            messages.error(request, _("У пациента нет телефона"))
        elif not wa_enabled():
            messages.error(request, _("WhatsApp не настроен"))
        else:
            ok = wa_send_text(patient.phone, text)
            WaMessage.objects.create(patient=patient, direction="out", phone=patient.phone,
                                     body=text, sent_by=request.user, ok=ok)
            if ok:
                messages.success(request, _("Сообщение отправлено в WhatsApp"))
                return redirect("patient_detail", pk=pk)
            messages.error(request, _("Не удалось отправить (проверьте номер/инстанс)"))

    if not MessageTemplate.objects.exists():
        from apps.notifications.whatsapp import seed_default_templates
        try:
            seed_default_templates()
        except Exception:
            pass
    tpls = [{"name": t.name, "body": render_message(t.body, patient=patient)}
            for t in MessageTemplate.objects.filter(is_active=True)]
    history = list(WaMessage.all_clinics.filter(patient=patient).order_by("created_at")[:300])
    return render(request, "patients/notify.html", {
        "patient": patient, "wa_templates": tpls, "wa_enabled": wa_enabled(),
        "wa_history": history,
    })


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
