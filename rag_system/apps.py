# rag_system/apps.py
from django.apps import AppConfig


class RagSystemConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rag_system'
    verbose_name = 'RAG System'

    def ready(self):
        # Import signals or other startup code
        try:
            import rag_system.signals
        except ImportError:
            pass