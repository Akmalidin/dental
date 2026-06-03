"""Создать клинику по умолчанию (SADAF) и привязать к ней все существующие данные."""
from django.db import migrations


SCOPED = [
    ("users", "Branch"), ("users", "User"),
    ("patients", "Patient"),
    ("treatments", "Treatment"), ("treatments", "MedicalRecordTemplate"),
    ("appointments", "Appointment"),
    ("services", "Service"), ("services", "ServiceCategory"),
    ("warehouse", "Product"), ("warehouse", "ProductCategory"), ("warehouse", "Supplier"),
    ("finance", "Payment"), ("finance", "Expense"), ("finance", "ExpenseCategory"),
    ("medicines", "Medicine"),
    ("settings_clinic", "DocumentTemplate"),
]


def forward(apps, schema_editor):
    Clinic = apps.get_model("users", "Clinic")
    clinic, _ = Clinic.objects.get_or_create(
        slug="sadaf", defaults={"name": "SADAF", "is_active": True}
    )
    for app_label, model_name in SCOPED:
        try:
            Model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        Model.objects.filter(clinic__isnull=True).update(clinic=clinic)


def backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_clinic_alter_branch_managers_branch_clinic_and_more"),
        ("patients", "0004_historicalpatient_clinic_patient_clinic"),
        ("treatments", "0008_alter_medicalrecordtemplate_managers_and_more"),
        ("appointments", "0006_appointment_clinic"),
        ("services", "0003_alter_service_managers_and_more"),
        ("warehouse", "0004_alter_product_managers_and_more"),
        ("finance", "0004_alter_expense_managers_and_more"),
        ("medicines", "0004_alter_medicine_managers_medicine_clinic"),
        ("settings_clinic", "0004_alter_documenttemplate_managers_and_more"),
    ]
    operations = [migrations.RunPython(forward, backward)]
