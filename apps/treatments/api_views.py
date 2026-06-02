from rest_framework import generics, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Treatment, TreatmentCure, TreatmentFollowUp
from .serializers import (
    TreatmentListSerializer, TreatmentDetailSerializer,
    TreatmentCureSerializer, TreatmentFollowUpSerializer,
)


class TreatmentListCreateAPIView(generics.ListCreateAPIView):
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["status", "doctor", "branch", "patient"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Treatment.objects.select_related("patient", "doctor", "branch")
        if self.request.user.is_doctor:
            qs = qs.filter(doctor=self.request.user)
        return qs

    def get_serializer_class(self):
        if self.request.method == "GET":
            return TreatmentListSerializer
        return TreatmentDetailSerializer


class TreatmentDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TreatmentDetailSerializer
    queryset = Treatment.objects.prefetch_related("cures__service", "files", "followups")


class TreatmentCureListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = TreatmentCureSerializer

    def get_queryset(self):
        return TreatmentCure.objects.filter(treatment_id=self.kwargs["treatment_pk"])


class TreatmentFollowUpListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = TreatmentFollowUpSerializer

    def get_queryset(self):
        return TreatmentFollowUp.objects.filter(treatment_id=self.kwargs["treatment_pk"])
