from django.contrib import admin
from .models import Payment, Expense, ExpenseCategory, PatientAdvance


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["patient", "amount", "method", "type", "received_by", "branch", "created_at"]
    list_filter = ["method", "type", "branch"]
    search_fields = ["patient__first_name", "patient__last_name"]
    date_hierarchy = "created_at"


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["category", "amount", "branch", "date", "created_by"]
    list_filter = ["category", "branch"]
    date_hierarchy = "date"


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ["name"]


@admin.register(PatientAdvance)
class PatientAdvanceAdmin(admin.ModelAdmin):
    list_display = ["patient", "amount", "date"]
