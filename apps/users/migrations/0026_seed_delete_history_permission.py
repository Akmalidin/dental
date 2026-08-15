from django.db import migrations

# Новое право «Удаление истории приёмов» — удаление записи из истории приёмов
# пациента (карта пациента → «История приёмов»), см. apps.treatments.views.
# treatment_delete. Действие необратимо влияет на историю пациента (хоть и
# мягкое удаление — «в корзину»), поэтому, в отличие от patients.delete,
# по умолчанию НЕ выдаётся роли «Администратор» — только директору клиники
# (admin_main) и суперадмину; сам директор решает, кому ещё это право нужно,
# через «Персонал → Роли».
# ВАЖНО: гранты — через .add(), не .set() (см. 0024_seed_quick_sale_permission.py) —
# иначе перезапись стёрла бы права, добавленные позже вручную через UI.
NEW_PERM = (
    "patients.delete_history", "patients", "Удаление истории приёмов",
    "Удаление записи из истории приёмов пациента — мягкое удаление, в корзину", 3,
)
DEFAULT_GRANT_ROLES = ["superadmin", "admin_main"]


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
        ("users", "0025_seed_technician_role"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
