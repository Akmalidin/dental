from django.db import migrations

CATALOG = [
    # (code, category, label, help_text, sort_order)
    ("finance.accept_payments", "finance", "Приём оплат", "", 1),
    ("finance.delete_payment", "finance", "Удаление платежей", "Необратимо — влияет на баланс пациента", 2),
    ("finance.manage_expenses", "finance", "Управление расходами", "", 3),
    ("patients.delete", "patients", "Удаление пациентов", "Мягкое удаление — в корзину", 1),
    ("patients.export", "patients", "Экспорт списка пациентов", "", 2),
    ("staff.manage", "staff", "Создание и редактирование сотрудников", "", 1),
    ("reports.view_finance", "reports", "Финансовый отчёт", "", 1),
    ("reports.view_doctors", "reports", "Отчёт по врачам", "", 2),
    ("reports.export", "reports", "Экспорт отчётов в Excel", "", 3),
]

# роль → коды прав, которые у неё должны быть по умолчанию (сохраняет
# текущее поведение существующих role_required(...) на местах, которые
# Task 4 переведёт на has_perm — без этого смена на новую систему проверки
# молча отобрала бы доступ у тех, у кого он есть сейчас)
DEFAULT_GRANTS = {
    "superadmin": [c for c, *_ in CATALOG],
    "admin_main": [c for c, *_ in CATALOG],
    "admin": [
        "finance.accept_payments", "finance.manage_expenses",
        "patients.delete", "patients.export",
        "reports.view_finance", "reports.view_doctors", "reports.export",
    ],
    "doctor": ["finance.accept_payments"],
    "nurse": [],
}


def seed(apps, schema_editor):
    Permission = apps.get_model("users", "Permission")
    Role = apps.get_model("users", "Role")
    for code, category, label, help_text, sort_order in CATALOG:
        Permission.objects.update_or_create(
            code=code,
            defaults={"category": category, "label": label, "help_text": help_text, "sort_order": sort_order},
        )
    # На проде эти 5 ролей уже существуют (реальные пользователи ими пользуются
    # сегодня) — но на чистой БД (новая установка/тестовая БД) их ещё нет,
    # т.к. раньше они не создавались миграцией. get_or_create вместо ".update()",
    # чтобы сидинг был идемпотентен и на пустой, и на боевой базе одинаково.
    for role_name in DEFAULT_GRANTS.keys():
        Role.objects.get_or_create(name=role_name, clinic=None, defaults={"is_system": True})
    # существующие 5 ролей (clinic=NULL) помечаем системными и раздаём права
    Role.objects.filter(clinic__isnull=True).update(is_system=True)
    for role_name, codes in DEFAULT_GRANTS.items():
        role = Role.objects.filter(name=role_name, clinic__isnull=True).first()
        if role is None:
            continue
        perms = Permission.objects.filter(code__in=codes)
        role.granular_permissions.set(perms)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0021_permission_role_clinic_role_is_system_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, noop),
    ]
