from django.urls import path

from . import views

urlpatterns = [
    path("chat/", views.ChatView.as_view(), name="chat"),
    path("chat/<uuid:pk>/", views.ConversationView.as_view(), name="conversation"),
    path("formations/", views.FormationListView.as_view(), name="formations"),
    path("health/", views.health, name="health"),
]
