# rag_system/services/embedding_service.py
"""
Embedding service — Gemini embeddings (RAG_CONFIG["EMBEDDING_MODEL"], 768 dims).
Replaces sentence-transformers/BGE to eliminate the ~1 GB PyTorch memory footprint.
"""
import pickle
import logging
import time
import numpy as np
from typing import List, Tuple, Dict, Any, Optional

from django.conf import settings
from ..models import DocumentChunk

logger = logging.getLogger(__name__)

_EMBED_DIM = 768  # requested from the model (output_dimensionality)
_BATCH = 50       # texts per embedding request


class EmbeddingService:

    def __init__(self):
        self.model_name = settings.RAG_CONFIG['EMBEDDING_MODEL']

    @property
    def _embedding_dim(self) -> int:
        return _EMBED_DIM

    # ── Core API call ─────────────────────────────────────────────────────────

    def _embed_texts(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, _EMBED_DIM), dtype=np.float32)
        api_key = getattr(settings, 'GEMINI_API_KEY', '')
        if not api_key:
            logger.warning('GEMINI_API_KEY not set — returning zero embeddings')
            return np.zeros((len(texts), _EMBED_DIM), dtype=np.float32)
        try:
            from google import genai
            from google.genai import types
            client  = genai.Client(api_key=api_key)
            cfg     = types.EmbedContentConfig(output_dimensionality=_EMBED_DIM)
            vectors = []
            # Many texts per request (the free tier limits requests per
            # minute), with a pause and retry when the limit is hit.
            for start in range(0, len(texts), _BATCH):
                part = texts[start:start + _BATCH]
                for attempt in range(4):
                    try:
                        resp = client.models.embed_content(
                            model    = self.model_name,
                            contents = part,
                            config   = cfg,
                        )
                        break
                    except Exception as exc:
                        if attempt < 3 and ('429' in str(exc) or 'RESOURCE_EXHAUSTED' in str(exc)
                                            or '503' in str(exc)):
                            time.sleep(15 * (attempt + 1))
                            continue
                        raise
                vectors.extend(e.values for e in resp.embeddings)
            return np.array(vectors, dtype=np.float32)
        except Exception as exc:
            logger.error('Gemini embedding error: %s', exc)
            return np.zeros((len(texts), _EMBED_DIM), dtype=np.float32)

    # ── Public encoding API ───────────────────────────────────────────────────

    def generate_embedding(self, text: str) -> np.ndarray:
        """Encode a single query string."""
        return self._embed_texts([text])[0]

    def generate_embeddings(self, texts: List[str]) -> np.ndarray:
        """Encode document chunks."""
        return self._embed_texts(texts)

    # ── Persist to DB ─────────────────────────────────────────────────────────

    def embed_document_chunks(self, chunks: List[DocumentChunk]) -> None:
        """Generate and store embeddings for a list of DocumentChunk objects."""
        if not chunks:
            return
        texts      = [c.content for c in chunks]
        embeddings = self.generate_embeddings(texts)
        for chunk, vec in zip(chunks, embeddings):
            chunk.embedding = pickle.dumps(vec.astype(np.float32))
            # Vectors from different models are not comparable; remember which
            # one made this vector so a model change triggers re-embedding.
            meta = dict(chunk.metadata or {})
            meta['embedding_model'] = self.model_name if np.any(vec) else ''
            chunk.metadata = meta
            chunk.save(update_fields=['embedding', 'metadata'])
        logger.debug('EmbeddingService: stored %d chunk embeddings', len(chunks))

    # ── Load from DB ──────────────────────────────────────────────────────────

    def load_embeddings(
        self,
        document_type: Optional[str] = None,
    ) -> Tuple[List[str], np.ndarray, List[Dict[str, Any]]]:
        """Load all embeddings from the database."""
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

        return texts, np.array(vecs, dtype=np.float32), meta

    # ── Backward-compat stubs ─────────────────────────────────────────────────

    def load_embeddings_from_file(
        self, document_type: str
    ) -> Tuple[List[str], np.ndarray, List[Dict[str, Any]]]:
        return self.load_embeddings(document_type)

    def save_embeddings_to_file(self, document_type: str) -> None:
        pass
