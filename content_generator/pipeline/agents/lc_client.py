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

def lc_generate(prompt: str, model: str = None) -> str:
    """Invoke ChatGroq via LangChain and return raw text.

    Pass model= to override the default (e.g. for translation tasks that
    need a more capable model than the default 8b-instant).
    """
    if model:
        llm = ChatGroq(model=model, api_key=GROQ_API_KEY, temperature=0.3, max_retries=3)
    else:
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


# ── RAG retriever (database chunks ranked with BM25) ─────────

def lc_retrieve(client_id: str, query: str, scope_ids: list[str] = None, k: int = 4) -> list[str]:
    """The k most relevant stored chunks for this client."""
    try:
        from .ingestion import query_collection
        return query_collection(client_id, query, n_results=k, scope_ids=scope_ids)
    except Exception:
        return []
