from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from .models import Product, WarehouseEntry, WarehouseDistribution, Supplier
from .forms import ProductForm, WarehouseEntryForm, WarehouseDistributionForm


@login_required
def warehouse_dashboard(request):
    products = Product.objects.select_related("category", "supplier").filter(is_active=True)
    low_stock = [p for p in products if p.is_low_stock]
    entries = WarehouseEntry.objects.select_related("product", "supplier").order_by("-date")[:30]
    distributions = WarehouseDistribution.objects.select_related("product", "branch", "issued_to").order_by("-date")[:30]
    return render(request, "warehouse/dashboard.html", {
        "products": products,
        "low_stock": low_stock,
        "entries": entries,
        "distributions": distributions,
    })


@login_required
def entry_list(request):
    entries = WarehouseEntry.objects.select_related("product", "supplier", "created_by").order_by("-date")
    return render(request, "warehouse/entries.html", {"entries": entries})


@login_required
def entry_create(request):
    from datetime import date as _date
    from .models import Supplier
    if request.method == "POST":
        def _num(v):
            return (str(v).replace(",", ".").strip() or "0")
        supplier_id = request.POST.get("supplier") or None
        the_date = request.POST.get("date") or _date.today()
        notes = request.POST.get("notes", "")
        products = request.POST.getlist("product")
        quantities = request.POST.getlist("quantity")
        prices = request.POST.getlist("price")
        count = 0
        for pid, qty, price in zip(products, quantities, prices):
            if pid and str(qty).strip():
                WarehouseEntry.objects.create(
                    product_id=pid, quantity=_num(qty), price=_num(price or 0),
                    supplier_id=supplier_id, date=the_date,
                    created_by=request.user, notes=notes,
                )
                count += 1
        if count:
            messages.success(request, _("Зафиксировано поступлений: %(n)s") % {"n": count})
            return redirect("entry_list")
        messages.error(request, _("Добавьте хотя бы одну позицию"))
    return render(request, "warehouse/entry_form.html", {
        "products": Product.objects.filter(is_active=True),
        "suppliers": Supplier.objects.filter(is_active=True),
    })


@login_required
def distribution_list(request):
    distributions = WarehouseDistribution.objects.select_related("product", "branch", "issued_to").order_by("-date", "-id")
    f = request.GET.get("f", "")
    if f == "auto":
        distributions = distributions.filter(notes__startswith="Автосписание")
    elif f == "manual":
        distributions = distributions.exclude(notes__startswith="Автосписание")
    return render(request, "warehouse/distributions.html", {"distributions": distributions[:500], "f": f})


@login_required
def distribution_create(request):
    form = WarehouseDistributionForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, _("Списание зафиксировано"))
        return redirect("distribution_list")
    return render(request, "warehouse/distribution_form.html", {"form": form})


# ─── Transfer ────────────────────────────────────────────────────────────────

@login_required
def transfer_list(request):
    from .models import WarehouseTransfer
    transfers = WarehouseTransfer.objects.select_related(
        "from_branch", "to_branch", "created_by"
    ).prefetch_related("items__product").order_by("-date")
    return render(request, "warehouse/transfers.html", {"transfers": transfers})


@login_required
def transfer_create(request):
    from .models import WarehouseTransfer, WarehouseTransferItem
    from apps.users.models import Branch
    if request.method == "POST":
        from_b = Branch.objects.filter(pk=request.POST.get("from_branch")).first()
        to_b = Branch.objects.filter(pk=request.POST.get("to_branch")).first()
        if from_b and to_b and from_b != to_b:
            transfer = WarehouseTransfer.objects.create(
                from_branch=from_b, to_branch=to_b,
                date=request.POST.get("date") or None,
                created_by=request.user,
                notes=request.POST.get("notes", ""),
            )
            product_ids = request.POST.getlist("product")
            quantities = request.POST.getlist("quantity")
            for pid, qty in zip(product_ids, quantities):
                if pid and qty:
                    WarehouseTransferItem.objects.create(
                        transfer=transfer, product_id=pid, quantity=qty
                    )
            messages.success(request, _("Перемещение создано"))
            return redirect("transfer_list")
        messages.error(request, _("Выберите разные филиалы"))
    return render(request, "warehouse/transfer_form.html", {
        "products": Product.objects.filter(is_active=True),
        "branches": Branch.objects.all(),
    })


# ─── Inventory ───────────────────────────────────────────────────────────────

@login_required
def inventory_list(request):
    from .models import InventoryDocument
    docs = InventoryDocument.objects.select_related("branch", "created_by").order_by("-date")
    return render(request, "warehouse/inventories.html", {"inventories": docs})


@login_required
def inventory_create(request):
    from .models import InventoryDocument, InventoryItem
    from apps.users.models import Branch
    if request.method == "POST":
        branch = Branch.objects.filter(pk=request.POST.get("branch")).first() or Branch.objects.first()
        doc = InventoryDocument.objects.create(
            branch=branch, date=request.POST.get("date") or None,
            created_by=request.user, notes=request.POST.get("notes", ""),
        )
        def _num(v):
            # accept both "0,000" (RU locale) and "0.000"
            return (str(v).replace(",", ".").strip() or "0")
        product_ids = request.POST.getlist("product")
        system_qtys = request.POST.getlist("system_qty")
        actual_qtys = request.POST.getlist("actual_qty")
        for pid, sq, aq in zip(product_ids, system_qtys, actual_qtys):
            if pid and str(aq).strip() != "":
                InventoryItem.objects.create(
                    document=doc, product_id=pid,
                    system_qty=_num(sq), actual_qty=_num(aq),
                )
        if request.POST.get("post"):
            doc.post()
            messages.success(request, _("Инвентаризация проведена, остатки скорректированы"))
        else:
            messages.success(request, _("Инвентаризация сохранена как черновик"))
        return redirect("inventory_list")
    products = Product.objects.filter(is_active=True)
    return render(request, "warehouse/inventory_form.html", {
        "products": products,
        "products_json": [{"id": p.pk, "name": p.name, "qty": float(p.quantity)} for p in products],
        "branches": Branch.objects.all(),
    })


@login_required
def inventory_post(request, pk):
    from .models import InventoryDocument
    doc = get_object_or_404(InventoryDocument, pk=pk)
    if request.method == "POST":
        doc.post()
        messages.success(request, _("Инвентаризация проведена"))
    return redirect("inventory_list")
