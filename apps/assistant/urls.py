from django.urls import path

from apps.assistant import views

urlpatterns = [
    path("conversation/", views.conversation, name="assistant_conversation"),
    path("conversation/clear/", views.conversation_clear,
         name="assistant_conversation_clear"),
]
