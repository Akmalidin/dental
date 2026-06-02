from celery import shared_task


@shared_task(name="apps.warehouse.tasks.check_low_stock")
def check_low_stock():
    from .models import Product
    from apps.notifications.utils import notify_admins

    low_stock = Product.objects.filter(is_active=True, quantity__lte=models_F_qty())
    if low_stock.exists():
        lines = [f"⚠️ Низкий остаток:\n"]
        for p in low_stock:
            lines.append(f"• {p.name}: {p.quantity} {p.unit} (мин: {p.min_qty})")
        notify_admins("\n".join(lines))


def models_F_qty():
    from django.db.models import F
    # placeholder — used inside filter
    pass
