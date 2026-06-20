"""Автозаполнение журнала посещений пациента при создании записи (Appointment)."""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="appointments.Appointment")
def create_patient_visit(sender, instance, created, **kwargs):
    if not created:
        return
    # отменённые записи не считаем посещением
    if getattr(instance, "status", "") == "cancelled":
        return
    from apps.patients.models import PatientVisit
    try:
        PatientVisit.objects.get_or_create(
            appointment=instance,
            defaults={
                "patient_id": instance.patient_id,
                "visited_at": instance.start_at,
                "doctor_id": instance.doctor_id,
                "purpose": (instance.service.name if instance.service_id else "") or "",
                "source": PatientVisit.SOURCE_AUTO,
                "clinic_id": getattr(instance, "clinic_id", None),
            },
        )
    except Exception:
        # автозаполнение не должно ломать создание записи
        pass
