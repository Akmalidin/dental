from rest_framework import serializers
from .models import Task


class TaskSerializer(serializers.ModelSerializer):
    assigned_to_names = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source="created_by.name", read_only=True)

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "assigned_to", "assigned_to_names",
            "created_by", "created_by_name", "due_date",
            "status", "priority", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_assigned_to_names(self, obj):
        return [u.name for u in obj.assigned_to.all()]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)
