from django.contrib import admin, messages

from .models import Candidature, Conversation, DocumentChunk, Formation, Message
from .services import notifications


@admin.register(Candidature)
class CandidatureAdmin(admin.ModelAdmin):
    list_display = ["reference", "prenom", "nom", "email", "telephone", "formation", "statut", "notification_envoyee", "created_at"]
    list_filter = ["statut", "notification_envoyee", "formation__ecole"]
    search_fields = ["prenom", "nom", "email", "telephone", "formation__specialite"]
    readonly_fields = ["reference", "conversation", "notification_envoyee", "created_at"]
    actions = ["resend_notification"]

    @admin.action(description="Renvoyer la notification à l'équipe")
    def resend_notification(self, request, queryset):
        for c in queryset:
            notifications.notify_team(c)
        self.message_user(request, f"{queryset.count()} notification(s) traitée(s).", messages.SUCCESS)


@admin.register(Formation)
class FormationAdmin(admin.ModelAdmin):
    list_display = ["specialite", "diplome", "ecole", "niveau_requis", "nationalite_requise", "bac_requis"]
    list_filter = ["ecole", "diplome"]
    search_fields = ["specialite", "diplome", "ecole"]


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ["role", "text", "created_at"]
    readonly_fields = fields


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "created_at", "updated_at"]
    inlines = [MessageInline]


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ["source", "chunk_index", "embedding_model"]
    search_fields = ["text"]
