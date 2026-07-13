import re

from django.db import migrations


def _normalize_phone(raw):
    d = "".join(ch for ch in (raw or "") if ch.isdigit())
    return d[-9:] if len(d) >= 9 else d


def backfill_phone_norm(apps, schema_editor):
    Patient = apps.get_model("patients", "Patient")
    for p in Patient.objects.all().iterator():
        norm = _normalize_phone(p.phone)
        if p.phone_norm != norm:
            Patient.objects.filter(pk=p.pk).update(phone_norm=norm)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0012_historicalpatient_phone_norm_historicalpatient_pin_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_phone_norm, noop),
    ]
