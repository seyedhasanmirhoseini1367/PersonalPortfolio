# rag_system/management/commands/debug_rag.py
from django.core.management.base import BaseCommand
from rag_system.models import Document, DocumentChunk
from rag_system.services.embedding_service import EmbeddingService
from rag_system.services.retrieval_service import RetrievalService


class Command(BaseCommand):
    help = 'Debug RAG system components'

    def handle(self, *args, **options):
        self.stdout.write("🔧 Debugging RAG System...")

        # Check documents and chunks
        self.stdout.write("\n📊 Database Status:")
        self.stdout.write(f"Documents: {Document.objects.count()}")
        self.stdout.write(f"Chunks: {DocumentChunk.objects.count()}")
        self.stdout.write(f"Chunks with embeddings: {DocumentChunk.objects.filter(embedding__isnull=False).count()}")

        # Test embedding service
        self.stdout.write("\n🔧 Testing Embedding Service...")
        try:
            embedding_service = EmbeddingService()
            test_text = "Hello world"
            embedding = embedding_service.generate_embedding(test_text)
            self.stdout.write(f"✓ Embedding generated: shape {embedding.shape}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Embedding service error: {e}"))

        # Test retrieval service
        self.stdout.write("\n🔧 Testing Retrieval Service...")
        try:
            retrieval_service = RetrievalService()
            results = retrieval_service.retrieve("test query", "project")
            self.stdout.write(f"✓ Retrieval test: found {len(results)} results")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Retrieval service error: {e}"))

        self.stdout.write(self.style.SUCCESS("\n🎉 Debug completed!"))