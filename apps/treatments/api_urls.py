from django.urls import path
from . import api_views

urlpatterns = [
    path("", api_views.TreatmentListCreateAPIView.as_view(), name="api_treatments"),
    path("<int:pk>/", api_views.TreatmentDetailAPIView.as_view(), name="api_treatment_detail"),
    path("<int:treatment_pk>/cures/", api_views.TreatmentCureListCreateAPIView.as_view(), name="api_treatment_cures"),
    path("<int:treatment_pk>/followups/", api_views.TreatmentFollowUpListCreateAPIView.as_view(), name="api_treatment_followups"),
]
