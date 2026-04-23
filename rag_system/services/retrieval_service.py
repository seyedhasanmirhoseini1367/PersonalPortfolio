# rag_system/services/retrieval_service.py
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from typing import List, Dict, Any, Optional
from .embedding_service import EmbeddingService

# Minimum cosine similarity to include a chunk in results.
_SIMILARITY_THRESHOLD = 0.10


class RetrievalService:
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.top_k = 5

    def retrieve(self, query: str, document_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return the top-k most relevant chunks for a query, deduplicated by document."""
        try:
            query_embedding = self.embedding_service.generate_embedding(query).reshape(1, -1)

            if document_type:
                texts, embeddings, metadata = self.embedding_service.load_embeddings_from_file(document_type)
                if len(embeddings) == 0:
                    texts, embeddings, metadata = self.embedding_service.load_embeddings(document_type)
            else:
                texts, embeddings, metadata = self.embedding_service.load_embeddings()

            if len(embeddings) == 0:
                return []

            similarities = cosine_similarity(query_embedding, embeddings)[0]
            top_indices = np.argsort(similarities)[-self.top_k:][::-1]

            # Keep one chunk per document (highest score wins) to prevent a
            # large PDF from monopolising all top-k slots.
            seen_docs: set = set()
            results = []
            for idx in top_indices:
                if similarities[idx] < _SIMILARITY_THRESHOLD:
                    continue
                doc_id = metadata[idx].get('document_id', '')
                if doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)
                results.append({
                    'content':    texts[idx],
                    'similarity': float(similarities[idx]),
                    'metadata':   metadata[idx],
                })

            return results

        except Exception as exc:
            print(f"Retrieval error: {exc}")
            return []

    def hybrid_retrieve(self, query: str, document_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Search across all document types, merge, and return the top-k unique documents."""
        if document_types is None:
            document_types = ['project', 'resume', 'blog', 'skill', 'project_documentation']

        all_results = []
        for doc_type in document_types:
            all_results.extend(self.retrieve(query, doc_type))

        # Sort by score descending
        all_results.sort(key=lambda x: x['similarity'], reverse=True)

        # Final dedup: one chunk per document across all types
        seen_docs: set = set()
        unique_results = []
        for result in all_results:
            doc_id = result['metadata'].get('document_id', '')
            if doc_id not in seen_docs:
                seen_docs.add(doc_id)
                unique_results.append(result)

        return unique_results[:self.top_k]
