"""Разовая очистка: убрать «<» и «>» из имён и текстовых полей, которые могли
прийти снаружи (WhatsApp/Telegram, запись с сайта) — защита от XSS в уже
сохранённых данных. Новые данные чистит apps.users.sanitize."""
import re

from django.db import migrations

ANGLE = re.compile(r"[<>]")
QUOTES = str.maketrans({'"': "”", "`": "ʼ"})

TARGETS = [
    ("patients", "Patient", ("first_name", "last_name", "middle_name", "phone", "phone2", "pin", "address",
                             "insurance_policy", "allergy", "blood_group", "notes")),
    ("patients", "Lead", ("name", "phone", "comment")),
    ("appointments", "Appointment", ("notes", "cancel_note")),
    ("notifications", "Notification", ("title", "body")),
    ("users", "DoctorReview", ("author", "text")),
    ("users", "ClinicAccessRequest", ("clinic_slug", "clinic_name", "contact_name", "phone", "email", "message")),
]


def clean(apps, schema_editor):
    from django.db.models import Q
    for app_label, model_name, fields in TARGETS:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        names = [f for f in fields if any(x.name == f for x in model._meta.fields)]
        if not names:
            continue
        q = Q()
        for f in names:
            for ch in '<>"`':
                q |= Q(**{f"{f}__contains": ch})
        for obj in model._base_manager.filter(q).iterator():
            upd = {f: ANGLE.sub("", getattr(obj, f)).translate(QUOTES) for f in names if isinstance(getattr(obj, f), str)}
            model._base_manager.filter(pk=obj.pk).update(**upd)


class Migration(migrations.Migration):
    dependencies = [
        ("patients", "0018_alter_historicalpatient_branch_alter_patient_branch"),
        ("appointments", "0012_alter_appointment_source"),
        ("notifications", "0017_wamessage_ai_status_wamessage_by_ai_and_more"),
        ("users", "0038_user_tg_notifications"),
    ]
    operations = [migrations.RunPython(clean, migrations.RunPython.noop)]
