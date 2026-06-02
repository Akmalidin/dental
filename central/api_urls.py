from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from apps.tenants.models import Tenant, Subscription


@api_view(["GET"])
@permission_classes([IsAdminUser])
def tenants_api(request):
    tenants = Tenant.objects.select_related("subscription").values(
        "id", "name", "slug", "owner_email", "is_active",
        "subscription__plan", "subscription__is_active", "subscription__is_blocked",
    )
    return Response(list(tenants))


urlpatterns = [
    path("tenants/", tenants_api, name="api_central_tenants"),
]
