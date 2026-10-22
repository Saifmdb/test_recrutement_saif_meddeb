from rest_framework import serializers

from .models import Formation, Message


class ChatRequestSerializer(serializers.Serializer):
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    message = serializers.CharField(max_length=2000, trim_whitespace=True)


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "text", "payload", "created_at"]


class FormationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Formation
        fields = ["id", "diplome", "specialite", "ecole", "niveau_requis", "nationalite_requise", "bac_requis"]
