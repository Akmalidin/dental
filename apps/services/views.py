from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from .models import Service, ServiceCategory
from .forms import ServiceForm, ServiceCategoryForm


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
