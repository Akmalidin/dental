from django.contrib import admin
from .models import Tenant, Domain, Subscription

try:
    from django_tenants.admin import TenantAdminMixin

    @admin.register(Tenant)
    class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
        list_display = ["name", "slug", "owner_email", "is_active", "created_at"]
        list_filter = ["is_active"]
        search_fields = ["name", "owner_email", "slug"]

except ImportError:

    @admin.register(Tenant)
    class TenantAdmin(admin.ModelAdmin):
        list_display = ["name", "slug", "owner_email", "is_active", "created_at"]
        list_filter = ["is_active"]
        search_fields = ["name", "owner_email", "slug"]


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ["domain", "tenant", "is_primary"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["tenant", "plan", "is_active", "is_blocked", "started_at", "expired_at"]
    list_filter = ["plan", "is_active", "is_blocked"]
