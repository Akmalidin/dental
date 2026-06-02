from django.urls import path
from . import api_views

urlpatterns = [
    path("login/", api_views.LoginAPIView.as_view(), name="api_login"),
    path("logout/", api_views.LogoutAPIView.as_view(), name="api_logout"),
    path("me/", api_views.MeAPIView.as_view(), name="api_me"),
    path("users/", api_views.UserListCreateAPIView.as_view(), name="api_users"),
    path("users/<int:pk>/", api_views.UserDetailAPIView.as_view(), name="api_user_detail"),
    path("branches/", api_views.BranchListCreateAPIView.as_view(), name="api_branches"),
    path("branches/<int:pk>/", api_views.BranchDetailAPIView.as_view(), name="api_branch_detail"),
    path("roles/", api_views.RoleListAPIView.as_view(), name="api_roles"),
]
