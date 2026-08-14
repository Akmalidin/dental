from django.db import migrations

# Новое право «Быстрая продажа» (касса создаёт оплаченный приём без
# предварительного визита врача, см. apps.treatments.views.treatment_create_quick).
# ВАЖНО: гранты добавляются через .add(), а не .set() — иначе перезапись
# полного списка одним новым правом стёрла бы права, добавленные позже вручную
# через UI «Персонал → Роли» (в отличие от 0022_seed_permissions.py, которая
# делает .set() безопасно только потому, что это первый посев M2M целиком).
NEW_PERM = (
    "finance.quick_sale", "finance", "Быстрая продажа (без приёма)",
    "Создание оплаченной услуги кассиром без предварительного визита врача — "
    "требует подтверждения врача", 4,
)
DEFAULT_GRANT_ROLES = ["superadmin", "admin_main", "admin", "doctor"]


def seed(apps, schema_editor):
    Permission = apps.get_model("users", "Permission")
    Role = apps.get_model("users", "Role")
    code, category, label, help_text, sort_order = NEW_PERM
    perm, _ = Permission.objects.update_or_create(
        code=code,
        defaults={"category": category, "label": label, "help_text": help_text, "sort_order": sort_order},
    )
    for role_name in DEFAULT_GRANT_ROLES:
        role = Role.objects.filter(name=role_name, clinic__isnull=True).first()
        if role:
            role.granular_permissions.add(perm)


def unseed(apps, schema_editor):
    apps.get_model("users", "Permission").objects.filter(code=NEW_PERM[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0023_user_menu_prefs"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
