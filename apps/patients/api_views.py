from rest_framework import generics, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Patient, Tag, LeadSource
from .serializers import PatientListSerializer, PatientDetailSerializer, TagSerializer, LeadSourceSerializer


class PatientListCreateAPIView(generics.ListCreateAPIView):
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["branch", "gender", "source"]
    search_fields = ["first_name", "last_name", "middle_name", "phone", "phone2"]
    ordering_fields = ["created_at", "last_name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Patient.objects.select_related("branch", "source").prefetch_related("tags")

    def get_serializer_class(self):
        if self.request.method == "GET":
            return PatientListSerializer
        return PatientDetailSerializer


class PatientDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PatientDetailSerializer
    queryset = Patient.objects.select_related("branch", "source", "created_by").prefetch_related("tags")


class TagListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = TagSerializer
    queryset = Tag.objects.all()


class LeadSourceListAPIView(generics.ListCreateAPIView):
    serializer_class = LeadSourceSerializer
    queryset = LeadSource.objects.filter(is_active=True)
