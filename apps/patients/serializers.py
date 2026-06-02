from rest_framework import serializers
from .models import Patient, Tag, LeadSource


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "color"]


class LeadSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadSource
        fields = ["id", "name"]


class PatientListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(read_only=True)
    debt = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Patient
        fields = [
            "id", "full_name", "first_name", "last_name", "middle_name",
            "phone", "birth_date", "age", "gender", "branch_name",
            "balance", "debt", "created_at",
        ]


class PatientDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(read_only=True)
    debt = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), source="tags", many=True, write_only=True, required=False
    )
    source = LeadSourceSerializer(read_only=True)
    source_id = serializers.PrimaryKeyRelatedField(
        queryset=LeadSource.objects.all(), source="source", write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Patient
        fields = [
            "id", "first_name", "last_name", "middle_name", "full_name",
            "birth_date", "age", "gender", "phone", "phone2", "address",
            "source", "source_id", "tags", "tag_ids", "branch", "balance",
            "debt", "notes", "created_at", "updated_at", "created_by",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "balance"]

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)
