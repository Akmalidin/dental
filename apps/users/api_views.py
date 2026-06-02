from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import login, logout
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter

from .models import User, Branch, Role
from .serializers import UserSerializer, UserMeSerializer, LoginSerializer, BranchSerializer, RoleSerializer


class LoginAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        login(request, user)
        return Response(UserMeSerializer(user).data)


class LogoutAPIView(APIView):
    def post(self, request):
        logout(request)
        return Response({"detail": "Выход выполнен"})


class MeAPIView(generics.RetrieveUpdateAPIView):
    serializer_class = UserMeSerializer

    def get_object(self):
        return self.request.user


class UserListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = UserSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["role__name", "is_active"]
    search_fields = ["name", "login", "email", "phone"]

    def get_queryset(self):
        return User.objects.select_related("role").prefetch_related("branches")


class UserDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UserSerializer
    queryset = User.objects.select_related("role").prefetch_related("branches")


class BranchListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = BranchSerializer
    queryset = Branch.objects.all()


class BranchDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = BranchSerializer
    queryset = Branch.objects.all()


class RoleListAPIView(generics.ListAPIView):
    serializer_class = RoleSerializer
    queryset = Role.objects.all()
