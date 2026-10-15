from django.db import migrations

# Правка платежа меняет баланс пациента — раньше была доступна любому
# сотруднику. Новое право; выдаём системным директору/администратору и всем
# ролям (в т.ч. своим ролям клиник), у которых уже есть «Управление
# расходами» — то есть тем, кто и так ведёт деньги клиники.
NEW_PERM = ("finance.edit_payment", "finance", "Изменение платежей", "Меняет баланс пациента", 2)


def seed(apps, schema_editor):
    Permission = apps.get_model("users", "Permission")
    Role = apps.get_model("users", "Role")
    code, category, label, help_text, sort_order = NEW_PERM
    perm, _ = Permission.objects.update_or_create(
        code=code, defaults={"category": category, "label": label, "help_text": help_text,
                             "sort_order": sort_order})
    roles = set(Role.objects.filter(name__in=["superadmin", "admin_main", "admin"], clinic__isnull=True))
    roles |= set(Role.objects.filter(granular_permissions__code="finance.manage_expenses"))
    for role in roles:
        role.granular_permissions.add(perm)


def unseed(apps, schema_editor):
    apps.get_model("users", "Permission").objects.filter(code=NEW_PERM[0]).delete()


class Migration(migrations.Migration):
    dependencies = [("users", "0039_technician_cashdesk_perms")]
    operations = [migrations.RunPython(seed, unseed)]
