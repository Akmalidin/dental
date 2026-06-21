from django.db import migrations


def fix_via_cashier(apps, schema_editor):
    """Платежи, принятые врачом, — это НЕ кассовые (через кассу их не отправляли).
    Оставляем via_cashier=True только у платежей, принятых не-врачом (кассиром/админом)."""
    from django.db.models import Q
    Payment = apps.get_model("finance", "Payment")
    User = apps.get_model("users", "User")
    doctor_ids = set(
        User.objects.filter(Q(role__name="doctor") | Q(roles__name="doctor"))
        .values_list("id", flat=True)
    )
    if doctor_ids:
        Payment.objects.filter(received_by_id__in=doctor_ids).update(via_cashier=False)


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0006_payment_via_cashier"),
    ]

    operations = [
        migrations.RunPython(fix_via_cashier, migrations.RunPython.noop),
    ]
