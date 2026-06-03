"""
Мягкое удаление (Корзина). Модель с этим миксином по умолчанию скрывает
удалённые записи во всех запросах (включая обратные связи), но их можно
восстановить из корзины.

Использование:
    class Patient(SoftDeleteModel):
        ...
    Patient.objects        -> только не удалённые (по умолчанию)
    Patient.all_objects    -> все, включая удалённые
    obj.soft_delete(user)  -> пометить удалённым
    obj.restore()          -> восстановить
"""
from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """Менеджер по умолчанию — отдаёт только не удалённые записи."""
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="Удалён")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Удалён в")
    deleted_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Кто удалил",
    )

    objects = SoftDeleteManager()          # по умолчанию — без удалённых
    all_objects = models.Manager()         # все записи

    class Meta:
        abstract = True
        base_manager_name = "all_objects"  # внутренние операции Django видят всё

    def soft_delete(self, user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if user is not None and getattr(user, "pk", None):
            self.deleted_by = user
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
