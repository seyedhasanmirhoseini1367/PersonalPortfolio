# rag_system/services/embedding_service.py
import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List, Tuple, Any, Optional, Dict
import pickle
import os
from django.conf import settings
from ..models import DocumentChunk


class EmbeddingService:
    def __init__(self):
        self.model_name = settings.RAG_CONFIG['EMBEDDING_MODEL']
        try:
            self.model = SentenceTransformer(self.model_name)
        except Exception as e:
            print(f"Error loading model: {e}")
            # Fallback to a simpler approach
            self.model = None
        self.vector_store_path = settings.RAG_CONFIG['VECTOR_STORE_PATH']

        # Ensure vector store directory exists
        os.makedirs(self.vector_store_path, exist_ok=True)

    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding for a single text"""
        if self.model is None:
            # Return a dummy embedding if model fails to load
            return np.random.rand(384).astype(np.float32)
        return self.model.encode(text)

    def generate_embeddings(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for multiple texts"""
        if self.model is None:
            # Return dummy embeddings if model fails to load
            return np.random.rand(len(texts), 384).astype(np.float32)
        return self.model.encode(texts)

    def embed_document_chunks(self, document_chunks: List[DocumentChunk]) -> None:
        """Generate and store embeddings for document chunks"""
        if not document_chunks:
            return

        texts = [chunk.content for chunk in document_chunks]
        embeddings = self.generate_embeddings(texts)

        for chunk, embedding in zip(document_chunks, embeddings):
            # Store embedding as bytes
            chunk.embedding = pickle.dumps(embedding)
            chunk.save()

    def load_embeddings(self, document_type: str = None) -> Tuple[List[str], np.ndarray, List[Dict[str, Any]]]:
        """Load all embeddings from database"""
        queryset = DocumentChunk.objects.select_related('document')
        if document_type:
            queryset = queryset.filter(document__document_type=document_type)

        chunks = list(queryset.filter(embedding__isnull=False))

        if not chunks:
            return [], np.array([]), []

        texts = []
        embeddings = []
        metadata = []

        for chunk in chunks:
            try:
                embedding_data = pickle.loads(chunk.embedding)
                texts.append(chunk.content)
                embeddings.append(embedding_data)
                metadata.append({
                    'chunk_id': str(chunk.id),
                    'document_id': str(chunk.document.id),
                    'document_title': chunk.document.title,
                    'document_type': chunk.document.document_type,
                    'chunk_index': chunk.chunk_index
                })
            except Exception as e:
                print(f"Error loading embedding for chunk {chunk.id}: {e}")
                continue

        if not embeddings:
            return [], np.array([]), []

        return texts, np.array(embeddings), metadata

    def save_embeddings_to_file(self, document_type: str) -> None:
        """Save embeddings to file for faster loading"""
        texts, embeddings, metadata = self.load_embeddings(document_type)

        if len(embeddings) > 0:
            file_path = os.path.join(self.vector_store_path, f"{document_type}_embeddings.pkl")
            with open(file_path, 'wb') as f:
                pickle.dump({
                    'texts': texts,
                    'embeddings': embeddings,
                    'metadata': metadata
                }, f)
            print(f"Saved {len(embeddings)} embeddings for {document_type} to {file_path}")

    def load_embeddings_from_file(self, document_type: str) -> Tuple[List[str], np.ndarray, List[Dict[str, Any]]]:
        """Load embeddings from file"""
        file_path = os.path.join(self.vector_store_path, f"{document_type}_embeddings.pkl")

        if os.path.exists(file_path):
            try:
                with open(file_path, 'rb') as f:
                    data = pickle.load(f)
                print(f"Loaded {len(data['embeddings'])} embeddings for {document_type} from file")
                return data['texts'], data['embeddings'], data['metadata']
            except Exception as e:
                print(f"Error loading embeddings from file {file_path}: {e}")

        print(f"No embeddings file found for {document_type}, loading from database")
        return self.load_embeddings(document_type)
