from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Conversation, DocumentChunk, Formation, Message
from .serializers import ChatRequestSerializer, FormationSerializer, MessageSerializer
from .services import agent, llm


class ChatView(APIView):
    """POST {conversation_id?, message} -> the assistant's answer (text + cards / recap / sources)."""

    def post(self, request):
        ser = ChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        conversation_id = ser.validated_data.get("conversation_id")
        text = ser.validated_data["message"]

        conversation = None
        if conversation_id:
            conversation = Conversation.objects.filter(id=conversation_id).first()
        if conversation is None:
            conversation = Conversation.objects.create(**({"id": conversation_id} if conversation_id else {}))

        Message.objects.create(conversation=conversation, role="user", text=text)
        result = agent.run(conversation, text)
        conversation.save()

        payload = {k: result[k] for k in ("cards", "recap", "sources", "confirmation")}
        answer = Message.objects.create(conversation=conversation, role="assistant", text=result["text"], payload=payload)
        return Response({"conversation_id": str(conversation.id), "message": MessageSerializer(answer).data})


class ConversationView(APIView):
    """Conversation history, to restore the chat after a page reload."""

    def get(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk)
        return Response({"conversation_id": str(conversation.id),
                         "messages": MessageSerializer(conversation.messages.all(), many=True).data})


class FormationListView(generics.ListAPIView):
    queryset = Formation.objects.all()
    serializer_class = FormationSerializer
    pagination_class = None


@api_view(["GET"])
def health(request):
    try:
        llm.chat([{"role": "user", "content": "ping"}], max_tokens=1)
        llm_ok = True
    except llm.LLMError:
        llm_ok = False  # health check only
    return Response({"llm": {"model": settings.LLM_CHAT_MODEL, "reachable": llm_ok},
                     "formations": Formation.objects.count(), "document_chunks": DocumentChunk.objects.count()})
