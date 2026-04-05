# rag_system/models.py
from django.db import models
import uuid


class ChatSession(models.Model):
    """A named conversation grouping multiple Q&A exchanges."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(
        max_length=200,
        default='New Chat',
        help_text='Auto-generated from the first question in the session',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Chat Session'
        verbose_name_plural = 'Chat Sessions'

    def __str__(self):
        return f'{self.title} ({self.created_at:%Y-%m-%d %H:%M})'

    def message_count(self):
        return self.messages.count()


class Document(models.Model):
    DOCUMENT_TYPES = [
        ('project', 'Project'),
        ('resume', 'Resume'),
        ('blog', 'Blog Post'),
        ('skill', 'Technical Skill'),
        ('project_documentation', 'Project Documentation (uploaded file)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    content = models.TextField()
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPES)
    source = models.CharField(max_length=255, help_text="Source file or URL")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['document_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.document_type})"


class DocumentChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    content = models.TextField()
    chunk_index = models.IntegerField()
    embedding = models.BinaryField(null=True, blank=True)  # Store vector embeddings
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  # Make sure this exists

    class Meta:
        unique_together = ['document', 'chunk_index']
        indexes = [
            models.Index(fields=['document', 'chunk_index']),
        ]

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.title}"


class QueryLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ChatSession,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    query = models.TextField()
    response = models.TextField()
    sources = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Query: {self.query[:50]}..."