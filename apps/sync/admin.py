from django.contrib import admin

from .models import SyncConflict, SyncDevice


@admin.register(SyncDevice)
class SyncDeviceAdmin(admin.ModelAdmin):
    list_display = ["id", "clinic", "name", "created_by", "is_active", "created_at", "last_sync_at"]
    list_filter = ["is_active", "clinic"]
    list_editable = ["is_active"]
    readonly_fields = ["clinic", "created_by", "created_at", "last_sync_at"]
    exclude = ["token_hash"]

    def has_add_permission(self, request):
        return False   # регистрируются только из офлайн-копии (токен выдаётся один раз)


@admin.register(SyncConflict)
class SyncConflictAdmin(admin.ModelAdmin):
    list_display = ["id", "clinic", "model_label", "object_pk", "object_repr", "resolved", "created_at"]
    list_filter = ["resolved", "clinic"]
