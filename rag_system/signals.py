# rag_system/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Document, QueryLog
from .services.embedding_service import EmbeddingService

@receiver(post_save, sender=Document)
def update_document_embeddings(sender, instance, created, **kwargs):
    """Update embeddings when document is saved"""
    if created or kwargs.get('update_fields') is None or 'content' in kwargs.get('update_fields', []):
        embedding_service = EmbeddingService()
        chunks = instance.chunks.all()
        if chunks.exists():
            embedding_service.embed_document_chunks(chunks)
            embedding_service.save_embeddings_to_file(instance.document_type)