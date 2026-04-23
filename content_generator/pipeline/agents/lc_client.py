"""
LangChain layer — LLM (ChatGroq) + direct ChromaDB retrieval.
"""
import time
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from ..config import GROQ_API_KEY, GROQ_MODEL

# ── Singleton ─────────────────────────────────────────────────
_llm = None


def get_llm() -> ChatGroq:
    global _llm
    if _llm is None:
        _llm = ChatGroq(
            model=GROQ_MODEL,
            api_key=GROQ_API_KEY,
            temperature=0.7,
            max_retries=3,
        )
    return _llm


# ── LLM call ─────────────────────────────────────────────────

def lc_generate(prompt: str) -> str:
    """Invoke ChatGroq via LangChain and return raw text."""
    llm = get_llm()
    for attempt in range(4):
        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            if attempt < 3:
                wait = 10 * (2 ** attempt)
                print(f"  LLM error ({e}) — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ── RAG retriever (direct ChromaDB — no LangChain wrapper) ───

def lc_retrieve(client_id: str, query: str, scope_ids: list[str] = None, k: int = 4) -> list[str]:
    """Query the client's ChromaDB collection directly."""
    try:
        from .ingestion import _get_collection, embed_query
        collection = _get_collection(client_id)
        where = None
        if scope_ids:
            where = {"scope_id": scope_ids[0]} if len(scope_ids) == 1 \
                else {"scope_id": {"$in": scope_ids}}
        results = collection.query(
            query_embeddings=[embed_query(query)],
            n_results=min(k, collection.count() or 1),
            where=where,
        )
        return results["documents"][0] if results.get("documents") else []
    except Exception:
        return []
