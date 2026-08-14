from django.db import migrations

# Новая системная роль «Техник» (Role.TECHNICIAN = "technician") — чтобы её
# можно было выбрать при создании/редактировании сотрудника. Без специальных
# грантов по умолчанию (как и у "nurse" в 0022_seed_permissions.py) — раздел
# «Техники» (/technicians/) сам по себе открыт любому авторизованному
# пользователю (@login_required, без role_required/has_perm), особые права
# роли здесь не нужны.
ROLE_NAME = "technician"


def seed(apps, schema_editor):
    Role = apps.get_model("users", "Role")
    Role.objects.get_or_create(name=ROLE_NAME, clinic=None, defaults={"is_system": True})


def unseed(apps, schema_editor):
    apps.get_model("users", "Role").objects.filter(name=ROLE_NAME, clinic__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0024_seed_quick_sale_permission"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
