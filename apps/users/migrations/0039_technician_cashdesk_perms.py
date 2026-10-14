from django.db import migrations

# Техник работает в своём кабинете и на кассе: приём оплат и быстрая продажа.
CODES = ["finance.accept_payments", "finance.quick_sale"]


def grant(apps, schema_editor):
    Permission = apps.get_model("users", "Permission")
    Role = apps.get_model("users", "Role")
    role = Role.objects.filter(name="technician", clinic__isnull=True).first()
    if role is None:
        return
    role.granular_permissions.add(*Permission.objects.filter(code__in=CODES))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0038_user_tg_notifications"),
        ("users", "0024_seed_quick_sale_permission"),
    ]
    operations = [migrations.RunPython(grant, noop)]
