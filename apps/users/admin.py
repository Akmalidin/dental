from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Role, Branch, UserActivity
from .models_salary import SalaryScheme, DoctorSchedule


@admin.register(SalaryScheme)
class SalarySchemeAdmin(admin.ModelAdmin):
    list_display = ["user", "scheme_type", "fixed_amount", "percent"]
    list_filter = ["scheme_type"]


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):
    list_display = ["doctor", "branch", "day_of_week", "start_time", "end_time", "is_working"]
    list_filter = ["day_of_week", "branch", "is_working"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["login", "name", "role", "is_active"]
    list_filter = ["role", "is_active"]
    search_fields = ["login", "name", "email"]
    fieldsets = (
        (None, {"fields": ("login", "password")}),
        ("Личные данные", {"fields": ("name", "email", "phone", "avatar", "telegram_id")}),
        ("Доступ", {"fields": ("role", "branches", "is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("login", "name", "email", "password1", "password2", "role"),
        }),
    )
    ordering = ["login"]
    filter_horizontal = ["branches"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name"]
    filter_horizontal = ["permissions"]


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["name", "address", "phone", "is_main", "is_active"]
    list_filter = ["is_main", "is_active"]


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ["user", "action", "model_name", "created_at"]
    list_filter = ["action"]
    readonly_fields = ["user", "action", "model_name", "object_id", "description", "ip_address", "created_at"]
