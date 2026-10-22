import uuid

from django.db import models


class Formation(models.Model):
    """One row of the Excel file "diplôme spécialité"."""

    diplome = models.CharField(max_length=150)
    specialite = models.CharField(max_length=255)
    ecole = models.CharField(max_length=100)
    niveau_requis = models.CharField(max_length=255, blank=True)
    nationalite_requise = models.CharField(max_length=100, blank=True)
    bac_requis = models.CharField(max_length=255, blank=True)
    search_text = models.TextField(blank=True, editable=False)

    class Meta:
        ordering = ["ecole", "diplome", "specialite"]

    def __str__(self):
        return f"{self.diplome} — {self.specialite} ({self.ecole})"


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # LLM message history (incl. tool calls) + pending registration recap
    state = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.id)


class Message(models.Model):
    """Messages displayed in the chat (what the UI shows)."""

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10)  # "user" | "assistant"
    text = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)  # cards, recap...
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class Candidature(models.Model):
    STATUT_NOUVELLE = "Nouvelle"

    prenom = models.CharField(max_length=80)
    nom = models.CharField(max_length=80)
    email = models.EmailField(unique=True)
    telephone = models.CharField(max_length=20, unique=True)  # normalised, e.g. +21622123456
    formation = models.ForeignKey(Formation, on_delete=models.PROTECT, related_name="candidatures")
    statut = models.CharField(max_length=30, default=STATUT_NOUVELLE)
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True)
    notification_envoyee = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def reference(self):
        return f"ADM-{self.pk:05d}" if self.pk else ""

    def __str__(self):
        return f"{self.reference} {self.prenom} {self.nom}"


class DocumentChunk(models.Model):
    """A chunk of the admission procedure document + its embedding (simple vector store)."""

    source = models.CharField(max_length=255)
    chunk_index = models.PositiveIntegerField()
    section = models.CharField(max_length=255, blank=True)
    text = models.TextField()
    embedding = models.JSONField(null=True, blank=True)
    embedding_model = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["source", "chunk_index"]
