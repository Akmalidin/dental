"""Backfill per-clinic sequential numbers for existing treatments.

Each clinic gets its own numbering starting from 1, ordered by creation (pk).
Soft-deleted treatments are numbered too, so the sequence never collides with
new treatments created afterwards. Mirrors patients/migrations/0007_backfill_patient_number.py.
"""
from django.db import migrations


def backfill_numbers(apps, schema_editor):
    Treatment = apps.get_model("treatments", "Treatment")
    by_clinic = {}
    for t in Treatment.objects.all().order_by("clinic_id", "pk"):
        by_clinic.setdefault(t.clinic_id, []).append(t)
    for clinic_id, treatments in by_clinic.items():
        n = 0
        for t in treatments:
            n += 1
            if t.number != n:
                t.number = n
                t.save(update_fields=["number"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("treatments", "0017_historicaltreatment_number_treatment_number"),
    ]

    operations = [
        migrations.RunPython(backfill_numbers, noop),
    ]
