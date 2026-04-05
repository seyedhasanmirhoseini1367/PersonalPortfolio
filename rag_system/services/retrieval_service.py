# rag_system/services/retrieval_service.py
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from typing import List, Dict, Any, Optional
from .embedding_service import EmbeddingService


class RetrievalService:
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.top_k = 5  # Number of chunks to retrieve

    def retrieve(self, query: str, document_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve most relevant chunks for a query"""
        try:
            # Generate query embedding
            query_embedding = self.embedding_service.generate_embedding(query).reshape(1, -1)

            # Load embeddings
            if document_type:
                texts, embeddings, metadata = self.embedding_service.load_embeddings_from_file(document_type)
                # If file loading fails or returns empty, try database
                if len(embeddings) == 0:
                    texts, embeddings, metadata = self.embedding_service.load_embeddings(document_type)
            else:
                texts, embeddings, metadata = self.embedding_service.load_embeddings()

            print(f"Retrieval: Found {len(embeddings)} embeddings for query: {query}")

            if len(embeddings) == 0:
                return []

            # Calculate similarities
            similarities = cosine_similarity(query_embedding, embeddings)[0]

            # Get top k results
            top_indices = np.argsort(similarities)[-self.top_k:][::-1]

            results = []
            for idx in top_indices:
                if similarities[idx] > 0.1:  # Similarity threshold
                    results.append({
                        'content': texts[idx],
                        'similarity': float(similarities[idx]),
                        'metadata': metadata[idx]
                    })

            print(f"Retrieval: Returning {len(results)} results")
            return results

        except Exception as e:
            print(f"Error in retrieval: {e}")
            return []

    def hybrid_retrieve(self, query: str, document_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Retrieve from multiple document types and merge results"""
        all_results = []

        if document_types is None:
            document_types = ['project', 'resume', 'blog', 'skill', 'project_documentation']

        print(f"Hybrid retrieval for query: {query}, types: {document_types}")

        for doc_type in document_types:
            results = self.retrieve(query, doc_type)
            all_results.extend(results)

        # Sort by similarity and remove duplicates
        all_results.sort(key=lambda x: x['similarity'], reverse=True)

        # Remove duplicates based on content
        seen_content = set()
        unique_results = []
        for result in all_results:
            content_hash = hash(result['content'][:100])  # Hash first 100 chars
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_results.append(result)

        final_results = unique_results[:self.top_k]
        print(f"Hybrid retrieval: Returning {len(final_results)} final results")
        return final_results