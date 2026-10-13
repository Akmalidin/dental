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


# ─── Лист ожидания: окно освободилось ───────────────────────────────────────
from django.db.models.signals import pre_save, post_delete  # noqa: E402

_FREEING = ("cancelled", "no_show")


@receiver(pre_save, sender="appointments.Appointment")
def _remember_old_slot(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._wl_old = None
        return
    instance._wl_old = (sender._base_manager.filter(pk=instance.pk)
                        .values("start_at", "end_at", "doctor_id", "branch_id", "status", "is_deleted").first())


def _freed(instance, start, end, doctor_id, branch_id):
    from django.utils import timezone
    if start and start > timezone.now() and doctor_id:
        from .waitlist import on_appointment_freed
        on_appointment_freed(instance.pk, instance.clinic_id, doctor_id, branch_id, start, end)


@receiver(post_save, sender="appointments.Appointment")
def _waitlist_on_change(sender, instance, created, raw=False, **kwargs):
    old = getattr(instance, "_wl_old", None)
    if raw or created or not old:
        return
    was_busy = old["status"] not in _FREEING and not old["is_deleted"]
    if not was_busy:
        return
    now_free = instance.status == "cancelled" or instance.is_deleted
    moved = (old["start_at"] != instance.start_at or old["doctor_id"] != instance.doctor_id)
    if now_free or moved:
        _freed(instance, old["start_at"], old["end_at"], old["doctor_id"], old["branch_id"])


@receiver(post_delete, sender="appointments.Appointment")
def _waitlist_on_delete(sender, instance, **kwargs):
    if instance.status not in _FREEING and not instance.is_deleted:
        _freed(instance, instance.start_at, instance.end_at, instance.doctor_id, instance.branch_id)
