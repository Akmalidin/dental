from django.urls import path
from . import api_views

urlpatterns = [
    path("", api_views.PatientListCreateAPIView.as_view(), name="api_patients"),
    path("<int:pk>/", api_views.PatientDetailAPIView.as_view(), name="api_patient_detail"),
    path("tags/", api_views.TagListCreateAPIView.as_view(), name="api_tags"),
    path("sources/", api_views.LeadSourceListAPIView.as_view(), name="api_lead_sources"),
]
