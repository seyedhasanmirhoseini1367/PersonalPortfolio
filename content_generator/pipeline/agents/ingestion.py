import shutil
import threading
import chromadb
from sentence_transformers import SentenceTransformer
from ..config import CHROMA_PATH

_model = SentenceTransformer("all-MiniLM-L6-v2")

_chroma_lock = threading.Lock()
_chroma_instance = None


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    return _model.encode(texts, convert_to_numpy=True).tolist()


def embed_query(query: str) -> list[float]:
    return _model.encode([query], convert_to_numpy=True)[0].tolist()


def _chroma_client() -> chromadb.PersistentClient:
    """Singleton PersistentClient — thread-safe, auto-heals corrupt DB."""
    global _chroma_instance
    with _chroma_lock:
        if _chroma_instance is not None:
            return _chroma_instance
        try:
            _chroma_instance = chromadb.PersistentClient(path=CHROMA_PATH)
        except Exception as e:
            if "tenant" in str(e).lower():
                shutil.rmtree(CHROMA_PATH, ignore_errors=True)
                _chroma_instance = chromadb.PersistentClient(path=CHROMA_PATH)
            else:
                raise
        return _chroma_instance


def _get_collection(client_id: str) -> chromadb.Collection:
    db = _chroma_client()
    try:
        return db.get_collection(name=f"client_{client_id}")
    except Exception:
        return db.create_collection(name=f"client_{client_id}")


def ingest_client_data(client_id: str, documents: list[str]) -> None:
    """Legacy: ingest raw documents without scope (used by CLI and guest form)."""
    if not documents:
        return
    db = _chroma_client()
    try:
        db.delete_collection(name=f"client_{client_id}")
    except Exception:
        pass
    collection = db.create_collection(name=f"client_{client_id}")

    all_chunks, all_ids, all_meta = [], [], []
    for i, doc in enumerate(documents):
        for j, chunk in enumerate(chunk_text(doc)):
            all_chunks.append(chunk)
            all_ids.append(f"{client_id}_{i}_{j}")
            all_meta.append({"scope_id": "general", "scope_name": "General"})

    embeddings = embed_texts(all_chunks)
    collection.add(documents=all_chunks, embeddings=embeddings, ids=all_ids, metadatas=all_meta)
    print(f"Ingested {len(all_chunks)} chunks for client '{client_id}'")


def ingest_scope_data(client_id: str, scope_id: str, scope_name: str, text: str) -> int:
    """Ingest text for a specific scope, appending to the company collection."""
    chunks = chunk_text(text)
    if not chunks:
        return 0

    collection = _get_collection(client_id)

    # Remove existing chunks for this scope_id to avoid duplicates on re-upload
    try:
        existing = collection.get(where={"scope_id": {"$eq": scope_id}})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    ids = [f"{client_id}_scope{scope_id}_{j}" for j in range(len(chunks))]
    meta = [{"scope_id": scope_id, "scope_name": scope_name} for _ in chunks]
    embeddings = embed_texts(chunks)
    collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=meta)
    return len(chunks)


def delete_scope_data(client_id: str, scope_id: str) -> None:
    """Remove all chunks for a scope from ChromaDB."""
    try:
        collection = _get_collection(client_id)
        existing = collection.get(where={"scope_id": {"$eq": scope_id}})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass


def query_collection(client_id: str, query: str, n_results: int = 5, scope_ids: list[str] = None) -> list[str]:
    """Retrieve relevant chunks via LangChain Chroma retriever with optional scope filter."""
    from .lc_client import lc_retrieve
    return lc_retrieve(client_id, query, scope_ids=scope_ids, k=n_results)


# Keep old name as alias
def get_collection(client_id: str):
    return _get_collection(client_id)
