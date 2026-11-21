"""
LLM layer — Gemini first, ChatGroq (LangChain) as fallback — plus chunk retrieval.
"""
import os
import time
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from ..config import GROQ_API_KEY, GROQ_MODEL, GEMINI_MODEL

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
            # Groq's free tier refuses any request that may produce more than
            # 1000 output tokens per minute; stay under it.
            max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "900")),
        )
    return _llm


# ── LLM call ─────────────────────────────────────────────────

def _gemini_generate(prompt: str, temperature: float) -> str | None:
    """Gemini first: its free tier allows long outputs, while Groq's free
    tier caps output at ~1000 tokens per minute (too little for a blog post).
    Returns None when Gemini is not configured or fails, so Groq takes over."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",   # every pipeline prompt asks for JSON
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return resp.text or None
    except Exception as e:
        print(f"  Gemini error ({str(e)[:160]}) — falling back to Groq")
        return None


def lc_generate(prompt: str, model: str = None) -> str:
    """Return the raw model text for a pipeline prompt.

    Tries Gemini first, then ChatGroq. Pass model= to use a larger Groq model
    for the fallback (e.g. translation).
    """
    text = _gemini_generate(prompt, 0.3 if model else 0.7)
    if text:
        return text
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
