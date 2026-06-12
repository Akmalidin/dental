"""Backfill per-clinic sequential numbers for existing patients.

Each clinic gets its own numbering starting from 1, ordered by creation (pk).
Soft-deleted patients are numbered too, so the sequence never collides with
new patients created afterwards.
"""
from django.db import migrations


def backfill_numbers(apps, schema_editor):
    Patient = apps.get_model("patients", "Patient")
    # Группируем по клинике (включая NULL — отдельная «группа»).
    by_clinic = {}
    for p in Patient.objects.all().order_by("clinic_id", "pk"):
        by_clinic.setdefault(p.clinic_id, []).append(p)
    for clinic_id, patients in by_clinic.items():
        n = 0
        for p in patients:
            n += 1
            if p.number != n:
                p.number = n
                p.save(update_fields=["number"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0006_historicalpatient_number_patient_number"),
    ]

    operations = [
        migrations.RunPython(backfill_numbers, noop),
    ]
