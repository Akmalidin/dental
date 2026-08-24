from django.db import migrations


def remove_permission(apps, schema_editor):
    """Удаление платежей больше не делегируется через RBAC-права (см.
    apps.finance.views.payment_delete — теперь require_superadmin, не
    require_permission) — убираем finance.delete_payment из каталога прав
    целиком, иначе чекбокс «Удаление платежей» в редакторе ролей остался бы
    висеть, ничего больше не давая (мёртвый, вводящий в заблуждение UI).
    Permission.code уникален, у М2М Role.granular_permissions удаление
    строки Permission каскадно чистит связи сама (through-таблица), другие
    модели на Permission не ссылаются."""
    Permission = apps.get_model("users", "Permission")
    Permission.objects.filter(code="finance.delete_payment").delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0033_clinicloginevent_attempted_login"),
    ]

    operations = [
        migrations.RunPython(remove_permission, noop),
    ]
