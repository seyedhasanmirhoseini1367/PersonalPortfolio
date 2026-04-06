# rag_system/services/embedding_service.py
"""
Embedding service — DB is the single source of truth.
Pkl cache files are no longer used; embeddings are always loaded fresh from
the DocumentChunk table. This ensures embeddings are never stale after
auto-sync signals fire.
"""
import pickle
import logging
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
from django.conf import settings
from ..models import DocumentChunk

logger = logging.getLogger(__name__)


class EmbeddingService:

    def __init__(self):
        self.model_name = settings.RAG_CONFIG['EMBEDDING_MODEL']
        self._model: Optional[SentenceTransformer] = None   # lazy-loaded

    # ── Model (lazy) ──────────────────────────────────────────────────────────

    @property
    def model(self) -> Optional[SentenceTransformer]:
        if self._model is None:
            try:
                self._model = SentenceTransformer(self.model_name)
                logger.debug('EmbeddingService: loaded model "%s"', self.model_name)
            except Exception as exc:
                logger.error('EmbeddingService: failed to load model "%s": %s', self.model_name, exc)
        return self._model

    # ── Encoding ──────────────────────────────────────────────────────────────

    def generate_embedding(self, text: str) -> np.ndarray:
        if self.model is None:
            return np.zeros(384, dtype=np.float32)
        return self.model.encode(text, show_progress_bar=False)

    def generate_embeddings(self, texts: List[str]) -> np.ndarray:
        if self.model is None:
            return np.zeros((len(texts), 384), dtype=np.float32)
        return self.model.encode(texts, show_progress_bar=False, batch_size=32)

    # ── Persist to DB ─────────────────────────────────────────────────────────

    def embed_document_chunks(self, chunks: List[DocumentChunk]) -> None:
        """Generate and store embeddings for a list of DocumentChunk objects."""
        if not chunks:
            return
        texts      = [c.content for c in chunks]
        embeddings = self.generate_embeddings(texts)
        for chunk, vec in zip(chunks, embeddings):
            chunk.embedding = pickle.dumps(vec.astype(np.float32))
            chunk.save(update_fields=['embedding'])
        logger.debug('EmbeddingService: stored %d chunk embeddings', len(chunks))

    # ── Load from DB ──────────────────────────────────────────────────────────

    def load_embeddings(
        self,
        document_type: Optional[str] = None,
    ) -> Tuple[List[str], np.ndarray, List[Dict[str, Any]]]:
        """
        Load all embeddings from the database.
        Returns (texts, embeddings_matrix, metadata_list).
        """
        qs = DocumentChunk.objects.select_related('document').filter(embedding__isnull=False)
        if document_type:
            qs = qs.filter(document__document_type=document_type)

        texts, vecs, meta = [], [], []
        for chunk in qs:
            try:
                vec = pickle.loads(chunk.embedding)
                texts.append(chunk.content)
                vecs.append(vec)
                meta.append({
                    'chunk_id':       str(chunk.id),
                    'document_id':    str(chunk.document.id),
                    'document_title': chunk.document.title,
                    'document_type':  chunk.document.document_type,
                    'chunk_index':    chunk.chunk_index,
                    'source':         chunk.document.source,
                })
            except Exception as exc:
                logger.debug('EmbeddingService: skipping chunk %s: %s', chunk.id, exc)

        if not vecs:
            return [], np.array([]), []

        logger.debug(
            'EmbeddingService: loaded %d embeddings (type=%s)',
            len(vecs), document_type or 'all',
        )
        return texts, np.array(vecs, dtype=np.float32), meta

    # ── Backward-compat stubs (pkl no longer used) ────────────────────────────

    def load_embeddings_from_file(
        self, document_type: str
    ) -> Tuple[List[str], np.ndarray, List[Dict[str, Any]]]:
        """Deprecated pkl path — now delegates straight to DB."""
        return self.load_embeddings(document_type)

    def save_embeddings_to_file(self, document_type: str) -> None:
        """No-op: pkl cache is removed. DB is the source of truth."""
        pass
