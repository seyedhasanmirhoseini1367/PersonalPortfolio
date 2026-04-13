# rag_system/graph/nodes.py
"""
LangGraph node functions.
Each function receives AgentState and returns a partial dict of updated fields.
LangGraph merges the returned dict back into the state automatically.
"""
import logging
from typing import Any, Dict

from .state import AgentState

logger = logging.getLogger(__name__)


# ── Router ────────────────────────────────────────────────────────────────────

_CV_KEYWORDS = {
    "who is hasan", "about you", "about hasan", "tell me about",
    "experience", "background", "education", "worked at", "career",
    "skills", "what do you do", "resume", "cv",
}
_THESIS_KEYWORDS = {
    "thesis", "seizure", "eeg", "epilepsy", "epileptic", "brain signal",
    "neural", "edf", "detection", "classification",
}
_ML_KEYWORDS = {
    "irrigation", "predict", "model demo", "prediction", "forecast",
    "machine learning", "ml model", "run model",
}
_PROJECT_KEYWORDS = {
    "project", "portfolio", "work", "built", "created", "developed",
    "kaggle", "competition", "github",
}


def router_node(state: AgentState) -> Dict[str, Any]:
    """Keyword-based router — assigns state['route'] without an LLM call."""
    question_lower = state["question"].lower()

    for keyword in _THESIS_KEYWORDS:
        if keyword in question_lower:
            logger.debug("router → thesis")
            return {"route": "thesis"}

    for keyword in _ML_KEYWORDS:
        if keyword in question_lower:
            logger.debug("router → ml_model")
            return {"route": "ml_model"}

    for keyword in _PROJECT_KEYWORDS:
        if keyword in question_lower:
            logger.debug("router → projects")
            return {"route": "projects"}

    for keyword in _CV_KEYWORDS:
        if keyword in question_lower:
            logger.debug("router → cv")
            return {"route": "cv"}

    logger.debug("router → general")
    return {"route": "general"}


# ── Search nodes ──────────────────────────────────────────────────────────────

def _retrieval_service():
    """Lazy import to avoid circular imports and cold-start cost."""
    from rag_system.services.retrieval_service import RetrievalService
    return RetrievalService()


def cv_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve from resume and skill document types."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=["resume", "skill"],
    )
    logger.debug("cv_node: retrieved %d chunks", len(chunks))
    return {"context_chunks": chunks}


def thesis_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve thesis / EEG / seizure related content."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=["project_documentation", "project"],
    )
    # Boost relevance by filtering on thesis-related terms if we got too many results
    thesis_terms = {"seizure", "eeg", "epilepsy", "thesis", "neural"}
    filtered = [
        c for c in chunks
        if any(t in c.get("content", "").lower() for t in thesis_terms)
    ]
    result_chunks = filtered if filtered else chunks
    logger.debug("thesis_node: retrieved %d chunks (%d after filter)", len(chunks), len(result_chunks))
    return {"context_chunks": result_chunks}


def ml_model_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve ML model documentation and optionally query Azure ML for status."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=["project", "project_documentation"],
    )

    ml_info: Dict[str, Any] = {}
    try:
        from projects.inference.azure_ml_client import AzureMLClient
        client = AzureMLClient()
        ml_info["azure_ml_configured"] = client.is_configured
        ml_info["azure_ml_status"]     = "ready" if client.is_configured else "not_configured"
    except Exception as exc:
        logger.warning("ml_model_node: could not check Azure ML: %s", exc)
        ml_info["azure_ml_status"] = "error"

    logger.debug("ml_model_node: retrieved %d chunks", len(chunks))
    return {"context_chunks": chunks, "ml_prediction": ml_info}


def projects_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve project and portfolio content."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=["project", "project_documentation"],
    )
    logger.debug("projects_node: retrieved %d chunks", len(chunks))
    return {"context_chunks": chunks}


def general_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve from all document types (fallback)."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=None,   # searches everything
    )
    logger.debug("general_node: retrieved %d chunks", len(chunks))
    return {"context_chunks": chunks}


# ── Generation ────────────────────────────────────────────────────────────────

def generate_node(state: AgentState) -> Dict[str, Any]:
    """Generate answer from retrieved context chunks."""
    from rag_system.services.generation_service import GenerationService
    generation = GenerationService()

    answer = generation.generate_response(
        question=state["question"],
        context_chunks=state.get("context_chunks", []),
        history=state.get("history", []),
    )
    logger.debug("generate_node: answer length=%d", len(answer))
    return {"answer": answer}


# ── Verification / self-correction ────────────────────────────────────────────

def verify_node(state: AgentState) -> Dict[str, Any]:
    """
    Quality check on the generated answer.
    If answer is too short or indicates uncertainty AND we haven't retried
    too many times, flag for retry.
    """
    answer      = state.get("answer", "")
    retry_count = state.get("retry_count", 0)

    low_quality_signals = [
        len(answer.strip()) < 50,
        "i don't know" in answer.lower(),
        "i cannot" in answer.lower() and len(answer) < 100,
        "no information" in answer.lower() and len(answer) < 100,
    ]

    if any(low_quality_signals) and retry_count < 2:
        logger.debug("verify_node: low quality answer, scheduling retry %d", retry_count + 1)
        return {"needs_retry": True, "retry_count": retry_count + 1}

    logger.debug("verify_node: answer accepted (retry_count=%d)", retry_count)
    return {"needs_retry": False}
