from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from .models import Service, ServiceCategory
from .forms import ServiceForm, ServiceCategoryForm


@login_required
def service_export(request):
    from .excel_io import export_services_xlsx
    return export_services_xlsx()


@login_required
@require_POST
def service_import(request):
    from .excel_io import import_services_xlsx
    f = request.FILES.get("file")
    if not f:
        messages.warning(request, _("Файл не выбран"))
        return redirect("service_list")
    try:
        created, updated, errors = import_services_xlsx(f)
        messages.success(request, _("Импорт: добавлено %(c)d, обновлено %(u)d") % {"c": created, "u": updated})
        if errors:
            messages.warning(request, "; ".join(errors[:5]))
    except Exception as e:
        messages.error(request, _("Ошибка импорта: %(e)s") % {"e": str(e)})
    return redirect("service_list")


@login_required
def service_list(request):
    q = request.GET.get("q", "")
    cat_id = request.GET.get("category", "")
    services = Service.objects.select_related("category").order_by("category__sort_order", "category__name", "name")
    if q:
        services = services.filter(name__icontains=q)
    if cat_id:
        services = services.filter(category_id=cat_id)
    categories = ServiceCategory.objects.order_by("sort_order", "name")
    return render(request, "services/list.html", {
        "services": services,
        "categories": categories,
        "q": q,
        "current_category": cat_id,
        "all_services_json": __import__("json").dumps(
            [{"id": s["id"], "name": s["name"], "price": float(s["price"]),
              "category__name": s["category__name"] or ""}
             for s in Service.objects.filter(is_active=True).select_related("category")
             .values("id", "name", "price", "category__name")],
            ensure_ascii=False
        ),
    })


@login_required
def category_create(request):
    """Create a service category (AJAX from the service form, or normal POST)."""
    from django.http import JsonResponse
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        color = request.POST.get("color", "#6366F1")
        if name:
            cat = ServiceCategory.objects.create(name=name, color=color)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "id": cat.pk, "name": cat.name})
            messages.success(request, _("Категория добавлена"))
    return redirect(request.META.get("HTTP_REFERER", "service_list"))


@login_required
def service_create(request):
    form = ServiceForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, _("Услуга добавлена"))
        return redirect("service_list")
    return render(request, "services/form.html", {"form": form})


@login_required
def service_edit(request, pk):
    service = get_object_or_404(Service, pk=pk)
    form = ServiceForm(request.POST or None, instance=service)
    if form.is_valid():
        form.save()
        messages.success(request, _("Услуга обновлена"))
        return redirect("service_list")
    return render(request, "services/form.html", {"form": form, "object": service})


@login_required
def service_delete(request, pk):
    service = get_object_or_404(Service, pk=pk)
    if request.method == "POST":
        service.is_active = False
        service.save()
        messages.success(request, _("Услуга деактивирована"))
        return redirect("service_list")
    return render(request, "services/confirm_delete.html", {"object": service})
