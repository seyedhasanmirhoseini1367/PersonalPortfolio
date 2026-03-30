# rag_system/management/commands/ingest_documents.py
from django.core.management.base import BaseCommand
from rag_system.services.document_processor import DocumentProcessor
from rag_system.services.embedding_service import EmbeddingService
import os
from django.conf import settings


class Command(BaseCommand):
    help = 'Ingest documents into the RAG system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--document-type',
            type=str,
            choices=['project', 'resume', 'blog', 'skill'],
            help='Specific document type to ingest'
        )

    def handle(self, *args, **options):
        processor = DocumentProcessor()
        embedding_service = EmbeddingService()

        documents_path = settings.RAG_CONFIG['DOCUMENTS_PATH']
        document_type = options['document_type']

        # Map document types to folders
        folders = {
            'project': 'projects',
            'resume': 'resume',
            'blog': 'blog_posts',
            'skill': 'technical_skills'
        }

        if document_type:
            folders = {document_type: folders[document_type]}

        for doc_type, folder in folders.items():
            folder_path = documents_path / folder
            if os.path.exists(folder_path):
                self.stdout.write(f"Processing {doc_type} documents...")
                self.process_folder(processor, embedding_service, folder_path, doc_type)

    def process_folder(self, processor, embedding_service, folder_path, document_type):
        """Process all files in a folder"""
        supported_extensions = ['.pdf', '.docx', '.txt', '.md']

        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path) and any(filename.lower().endswith(ext) for ext in supported_extensions):
                try:
                    self.stdout.write(f"Processing {filename}...")

                    # Process document
                    title = os.path.splitext(filename)[0].replace('_', ' ').title()
                    document = processor.process_document(file_path, document_type, title)

                    # Generate embeddings for chunks
                    chunks = document.chunks.all()
                    embedding_service.embed_document_chunks(chunks)

                    # Save embeddings to file
                    embedding_service.save_embeddings_to_file(document_type)

                    self.stdout.write(
                        self.style.SUCCESS(f"✓ Successfully processed {filename}")
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"✗ Error processing {filename}: {str(e)}")
                    )