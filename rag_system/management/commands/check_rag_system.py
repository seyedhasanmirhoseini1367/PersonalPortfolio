# rag_system/management/commands/check_rag_system.py
from django.core.management.base import BaseCommand
from rag_system.models import Document, DocumentChunk
from rag_system.services.embedding_service import EmbeddingService


class Command(BaseCommand):
    help = 'Check RAG system status and statistics'

    def handle(self, *args, **options):
        self.stdout.write("🤖 RAG System Status Check")
        self.stdout.write("=" * 50)

        # Document statistics
        total_docs = Document.objects.count()
        total_chunks = DocumentChunk.objects.count()
        chunks_with_embeddings = DocumentChunk.objects.filter(embedding__isnull=False).count()

        self.stdout.write(f"📊 Documents: {total_docs}")
        self.stdout.write(f"📄 Chunks: {total_chunks}")
        self.stdout.write(f"🔢 Chunks with embeddings: {chunks_with_embeddings}")

        # Document type breakdown
        self.stdout.write("\n📁 Document Types:")
        for doc_type, label in Document.DOCUMENT_TYPES:
            count = Document.objects.filter(document_type=doc_type).count()
            self.stdout.write(f"  {label}: {count}")

        # Check embedding service
        try:
            embedding_service = EmbeddingService()
            self.stdout.write(f"\n🔧 Embedding Model: {embedding_service.model_name}")
            self.stdout.write("✅ Embedding service is working")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Embedding service error: {e}"))

        self.stdout.write(self.style.SUCCESS("\n🎉 RAG system check completed!"))