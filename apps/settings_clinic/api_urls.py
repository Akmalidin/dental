from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import ClinicSettings
from .serializers import ClinicSettingsSerializer


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def clinic_settings_api(request):
    instance = ClinicSettings.get()
    if request.method == "GET":
        return Response(ClinicSettingsSerializer(instance).data)
    serializer = ClinicSettingsSerializer(instance, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


urlpatterns = [
    path("", clinic_settings_api, name="api_clinic_settings"),
]
