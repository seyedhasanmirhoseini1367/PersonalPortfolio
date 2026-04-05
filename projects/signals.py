# projects/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Projects


@receiver(post_save, sender=Projects)
def process_project_rag_document(sender, instance, created, **kwargs):
    """Auto-process RAG document when project is saved with a new document"""
    if instance.rag_document and not instance.rag_document_processed:
        import threading
        threading.Thread(target=instance.process_rag_document).start()