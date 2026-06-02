from django.urls import path
from rest_framework import generics
from .models import Medicine, PatientMedicine
from .serializers import MedicineSerializer, PatientMedicineSerializer


class MedicineListAPIView(generics.ListCreateAPIView):
    serializer_class = MedicineSerializer
    queryset = Medicine.objects.filter(is_active=True)


class PatientMedicineListAPIView(generics.ListCreateAPIView):
    serializer_class = PatientMedicineSerializer

    def get_queryset(self):
        qs = PatientMedicine.objects.select_related("medicine", "doctor", "patient")
        patient = self.request.query_params.get("patient")
        if patient:
            qs = qs.filter(patient_id=patient)
        return qs


urlpatterns = [
    path("", MedicineListAPIView.as_view(), name="api_medicines"),
    path("prescriptions/", PatientMedicineListAPIView.as_view(), name="api_prescriptions"),
]
