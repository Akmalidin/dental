from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, Role, Branch


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "name", "address", "phone", "is_main", "is_active"]


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name"]


class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), source="role", write_only=True, required=False
    )
    branches = BranchSerializer(many=True, read_only=True)
    branch_ids = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), source="branches", many=True, write_only=True, required=False
    )

    class Meta:
        model = User
        fields = [
            "id", "login", "name", "email", "phone", "avatar",
            "role", "role_id", "branches", "branch_ids",
            "telegram_id", "is_active",
        ]
        read_only_fields = ["id"]


class UserMeSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(read_only=True)
    branches = BranchSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "login", "name", "email", "phone", "avatar", "role_name", "branches"]


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data["login"], password=data["password"])
        if not user:
            raise serializers.ValidationError("Неверный логин или пароль")
        if not user.is_active:
            raise serializers.ValidationError("Аккаунт деактивирован")
        data["user"] = user
        return data
