"""Company knowledge for the content pipeline: store chunks, find relevant ones.

Chunks live in the database (content_generator.KnowledgeChunk) so they survive
deploys, and are ranked with BM25 (rank-bm25). This replaces ChromaDB +
sentence-transformers, which were missing from the production image and would
not fit in the small instance's memory (PyTorch alone is ~1 GB).
"""
import re

from rank_bm25 import BM25Okapi

_WORD = re.compile(r"[\w']+", re.UNICODE)
_STOP = {
    'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'with', 'is', 'are', 'be',
    'our', 'we', 'you', 'your', 'it', 'its', 'this', 'that', 'as', 'at', 'by', 'from', 'about',
}


def tokenize(text: str) -> list[str]:
    words = [w.lower() for w in _WORD.findall(text or '')]
    # light stemming so "services"/"service", "clinics"/"clinic" match
    return [w[:-1] if len(w) > 4 and w.endswith('s') else w for w in words if w not in _STOP]


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    words = (text or '').split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


def _store(client_id: str, scope_id: str, scope_name: str, chunks: list[str]) -> None:
    from content_generator.models import KnowledgeChunk
    KnowledgeChunk.objects.bulk_create([
        KnowledgeChunk(client_id=client_id, scope_id=scope_id, scope_name=scope_name, position=i, text=c)
        for i, c in enumerate(chunks)
    ])


def ingest_client_data(client_id: str, documents: list[str]) -> None:
    """Replace everything stored for client_id with these documents."""
    from content_generator.models import KnowledgeChunk
    if not documents:
        return
    KnowledgeChunk.objects.filter(client_id=client_id).delete()
    chunks = [c for doc in documents for c in chunk_text(doc)]
    _store(client_id, 'general', 'General', chunks)


def ingest_scope_data(client_id: str, scope_id: str, scope_name: str, text: str) -> int:
    """Replace the chunks of one scope (e.g. a service) for this client."""
    from content_generator.models import KnowledgeChunk
    KnowledgeChunk.objects.filter(client_id=client_id, scope_id=scope_id).delete()
    chunks = chunk_text(text)
    _store(client_id, scope_id, scope_name, chunks)
    return len(chunks)


def delete_scope_data(client_id: str, scope_id: str) -> None:
    from content_generator.models import KnowledgeChunk
    KnowledgeChunk.objects.filter(client_id=client_id, scope_id=scope_id).delete()


def query_collection(client_id: str, query: str, n_results: int = 5, scope_ids: list[str] = None) -> list[str]:
    """The n_results chunks most relevant to query (BM25), optionally within scopes."""
    from content_generator.models import KnowledgeChunk
    qs = KnowledgeChunk.objects.filter(client_id=client_id)
    if scope_ids:
        qs = qs.filter(scope_id__in=scope_ids)
    texts = list(qs.values_list('text', flat=True))
    if not texts:
        return []
    tokens = tokenize(query)
    if not tokens:
        return texts[:n_results]
    scores = BM25Okapi([tokenize(t) or ['_'] for t in texts]).get_scores(tokens)
    ranked = sorted(range(len(texts)), key=lambda i: scores[i], reverse=True)
    return [texts[i] for i in ranked[:n_results]]


def scope_names(client_id: str) -> list[tuple[str, str]]:
    from content_generator.models import KnowledgeChunk
    return list(KnowledgeChunk.objects.filter(client_id=client_id)
                .values_list('scope_id', 'scope_name').distinct())


def ensure_company_indexed(profile) -> None:
    """Index a company profile (about text + services) if nothing is stored yet.

    Profiles saved while indexing was broken have no chunks; this fills them
    in on the first generation instead of producing content with no context.
    """
    from content_generator.models import KnowledgeChunk
    client_id = f"company_{profile.pk}"
    if KnowledgeChunk.objects.filter(client_id=client_id).exists():
        return
    if profile.about:
        ingest_scope_data(client_id, 'about', 'Company About', profile.about)
    for service in profile.services.all():
        if service.description:
            ingest_scope_data(client_id, f"service_{service.pk}", service.name, service.description)
