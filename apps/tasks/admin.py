from django.contrib import admin
from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "priority", "status", "created_by", "due_date"]
    list_filter = ["status", "priority"]
    filter_horizontal = ["assigned_to"]
