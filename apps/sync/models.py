from django.db import models
from django.conf import settings


class SyncConflict(models.Model):
    """Конфликт синхронизации: одна и та же запись была изменена и локально
    (в оффлайн-копии клиники), и в облаке — после последней успешной
    синхронизации. Автоматически сторону не выбираем (риск молча потерять
    чьи-то правки): облачная версия остаётся рабочей как есть, а обе версии
    сохраняются здесь для ручного разрешения персоналом клиники."""

    RESOLUTION_CLOUD = "cloud"
    RESOLUTION_LOCAL = "local"
    RESOLUTION_CHOICES = [
        (RESOLUTION_CLOUD, "Оставили облачную версию"),
        (RESOLUTION_LOCAL, "Применили локальную версию"),
    ]

    clinic = models.ForeignKey(
        "users.Clinic", on_delete=models.CASCADE, related_name="sync_conflicts", verbose_name="Клиника",
    )
    model_label = models.CharField(max_length=100, verbose_name="Модель")
    object_pk = models.CharField(max_length=64, verbose_name="ID записи")
    object_repr = models.CharField(max_length=300, blank=True, verbose_name="Описание записи")
    local_data = models.JSONField(verbose_name="Локальная версия (офлайн)")
    cloud_data = models.JSONField(null=True, blank=True, verbose_name="Облачная версия (на момент конфликта)")
    local_updated_at = models.DateTimeField(null=True, blank=True)
    cloud_updated_at = models.DateTimeField(null=True, blank=True)

    resolved = models.BooleanField(default=False, db_index=True)
    resolution = models.CharField(max_length=10, blank=True, choices=RESOLUTION_CHOICES)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Конфликт синхронизации"
        verbose_name_plural = "Конфликты синхронизации"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.model_label} #{self.object_pk}"

    @property
    def diff_fields(self):
        """Список полей, различающихся между локальной и облачной версией."""
        local_f = (self.local_data or {}).get("fields", {})
        cloud_f = (self.cloud_data or {}).get("fields", {}) if self.cloud_data else {}
        keys = sorted(set(local_f) | set(cloud_f))
        return [
            {"field": k, "local": local_f.get(k), "cloud": cloud_f.get(k)}
            for k in keys if local_f.get(k) != cloud_f.get(k)
        ]
