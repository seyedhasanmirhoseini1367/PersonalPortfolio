# rag_system/services/retrieval_service.py
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from typing import List, Dict, Any, Optional
from .embedding_service import EmbeddingService

# Minimum cosine similarity to include a chunk in results.
# BGE-small scores are higher than MiniLM (0.5+ range), so 0.45 filters
# truly unrelated documents without cutting off legitimate matches.
_SIMILARITY_THRESHOLD = 0.45

# Per-intent document-type boosts applied BEFORE ranking so the right
# documents win without any hard-coded ordering workarounds.
# Values are added to the raw cosine similarity score.
_INTENT_BOOSTS: Dict[str, Dict[str, float]] = {
    "job_fit":  {"resume": 0.20, "skill": 0.08},
    "cv":       {"resume": 0.15, "skill": 0.05},
    "thesis":   {"project_documentation": 0.12},
    "ml_model": {"project_documentation": 0.10},
    "projects": {"project": 0.08},
    "general":  {},
}


class RetrievalService:
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.top_k = 5

    def retrieve(
        self,
        query: str,
        document_type: Optional[str] = None,
        intent: str = "",
    ) -> List[Dict[str, Any]]:
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
            similarities = self._apply_boost(
                query, similarities, metadata,
                intent=intent, doc_type=document_type or "",
            )
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

    _BOOST_STOP = frozenset({
        'any', 'a', 'an', 'the', 'is', 'are', 'was', 'what', 'which',
        'how', 'can', 'do', 'tell', 'about', 'for', 'me', 'you', 'i',
        'have', 'has', 'did', 'on', 'in', 'at', 'of', 'to', 'and', 'or',
        'his', 'her', 'their', 'your', 'my', 'explain', 'describe', 'show',
    })

    def _query_keywords(self, query: str) -> set:
        return {w for w in query.lower().split()
                if w not in self._BOOST_STOP and len(w) > 2}

    def _apply_boost(
        self,
        query: str,
        similarities: np.ndarray,
        metadata: list,
        intent: str = "",
        doc_type: str = "",
    ) -> np.ndarray:
        """
        Two-layer boost applied BEFORE top-k selection:

        1. Title-keyword boost (+8% per query keyword found in the document title)
           — helps surface the most directly named document.

        2. Intent-aware doc-type boost (from _INTENT_BOOSTS)
           — shifts the entire score distribution for a document type based on
           what the user's query is actually *about*, bridging the vocabulary
           gap between query language and document language.
           e.g. job_fit → resume +0.20 so the CV always outranks project docs
           even when the job posting happens to share more vocabulary with them.
        """
        boosted = similarities.copy()

        # Layer 1: title keyword boost
        words = self._query_keywords(query)
        if words:
            for i, meta in enumerate(metadata):
                title = meta.get('document_title', '').lower()
                matched = sum(1 for w in words if w in title)
                if matched:
                    boosted[i] += matched * 0.08

        # Layer 2: intent-aware doc-type boost (uniform across all chunks of this type)
        if intent and doc_type:
            type_boost = _INTENT_BOOSTS.get(intent, {}).get(doc_type, 0.0)
            if type_boost:
                boosted += type_boost

        return boosted

    def hybrid_retrieve(
        self,
        query: str,
        document_types: Optional[List[str]] = None,
        top_k: Optional[int] = None,
        intent: str = "",
    ) -> List[Dict[str, Any]]:
        """Search across all document types, merge, and return the top-k unique documents."""
        if document_types is None:
            document_types = ['project', 'resume', 'blog', 'skill', 'project_documentation']

        all_results = []
        for doc_type in document_types:
            all_results.extend(self.retrieve(query, doc_type, intent=intent))

        # Sort by boosted score descending
        all_results.sort(key=lambda x: x['similarity'], reverse=True)

        # Final dedup: one chunk per document across all types
        seen_docs: set = set()
        unique_results = []
        for result in all_results:
            doc_id = result['metadata'].get('document_id', '')
            if doc_id not in seen_docs:
                seen_docs.add(doc_id)
                unique_results.append(result)

        limit = top_k if top_k is not None else self.top_k
        return unique_results[:limit]
