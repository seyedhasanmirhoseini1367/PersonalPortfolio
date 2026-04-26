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

_JOB_FIT_KEYWORDS = {
    # Job description / posting matching
    "job description", "job posting", "job fit", "job opening",
    "good fit", "fit for this", "fit for the", "match for this",
    "we are looking for", "we're looking for",
    "requirements:", "qualifications:", "responsibilities:",
    "years of experience", "must have", "nice to have",
    "evaluate fit", "assess fit", "check fit",
    "am i a good fit", "is he a good fit", "would hasan fit",
    "hiring for", "open position", "apply for",
    # Competency / seniority evaluation
    "competency", "competencies", "seniority",
    "senior ml", "senior data", "senior engineer",
    "qualified for", "ready to be", "ready for a",
    "fit as a", "fit for a",
    "is he qualified", "is he ready", "does he have the",
    "what level", "which level", "level of engineer",
    "can he work as", "could he work as",
    "is hasan", "does hasan have",
    "junior or senior", "mid-level", "lead engineer",
}

_CV_KEYWORDS = {
    "who is hasan", "about you", "about hasan", "tell me about",
    "experience", "background", "education", "worked at", "career",
    "skills", "what do you do", "resume", "cv", "certification",
    "language", "degree", "university", "master", "bachelor",
    # Portfolio / project highlights are stored in the resume document
    "rag", "langchain", "langgraph", "chromadb", "groq", "gemini",
    "healthcompass", "casvuai", "hasanai", "multi-agent", "multiagent",
    "what has he", "what projects", "which projects", "portfolio",
}
_THESIS_KEYWORDS = {
    "thesis", "seizure", "eeg", "epilepsy", "epileptic", "brain signal",
    "edf", "detection", "classification", "cnn", "lstm", "transformer",
    "stft", "signal processing",
    "eeg foundation", "brain", "neural signal",
}
_ML_KEYWORDS = {
    "irrigation", "predict", "model demo", "prediction", "forecast",
    "ml model", "run model", "introvert", "extrovert", "personality",
    "foundation model", "pretrain", "pretraining", "self-supervised",
    "vicreg", "fine-tun", "neurips", "nips", "time-series model",
}
_PROJECT_KEYWORDS = {
    "built", "created", "developed", "implemented",
    "kaggle", "competition", "github",
    # domain / modality questions → list projects
    "computer vision", "image classification", "object detection", "image recognition",
    "nlp", "natural language", "sentiment", "text classification", "language model",
    "fraud", "churn", "customer", "credit card",
    "house price", "stock", "time series", "forecasting",
    "regression", "clustering", "reinforcement",
    "what project", "which project", "any project", "has he", "does he have",
    "show me", "list", "ml project", "deep learning project",
    "x-ray", "medical", "pneumonia", "chest",
}


def router_node(state: AgentState) -> Dict[str, Any]:
    """Keyword-based router — assigns state['route'] without an LLM call."""
    question_lower = state["question"].lower()

    for keyword in _JOB_FIT_KEYWORDS:
        if keyword in question_lower:
            logger.debug("router → job_fit")
            return {"route": "job_fit"}

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
    """Retrieve from resume, skill, and project text (highlights are in resume)."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=["resume", "skill", "project"],
        intent="cv",
    )
    logger.debug("cv_node: retrieved %d chunks", len(chunks))
    return {"context_chunks": chunks}


def thesis_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve thesis / EEG / seizure related content."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=["project_documentation", "project"],
        intent="thesis",
    )
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
        intent="ml_model",
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
    """Retrieve project and portfolio content, including resume highlights."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=["project", "project_documentation", "resume"],
        intent="projects",
    )
    logger.debug("projects_node: retrieved %d chunks", len(chunks))
    return {"context_chunks": chunks}


def general_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve from all document types (fallback)."""
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=None,
        intent="general",
    )
    logger.debug("general_node: retrieved %d chunks", len(chunks))
    return {"context_chunks": chunks}


def job_fit_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve resume + skills + projects for job-fit analysis.

    The intent='job_fit' boost (+0.20 on resume, +0.08 on skill) ensures the
    resume always outranks project documents in similarity scoring, bridging the
    vocabulary gap where job postings share more domain keywords with project
    docs than with the candidate's CV.
    """
    retrieval = _retrieval_service()
    chunks = retrieval.hybrid_retrieve(
        query=state["question"],
        document_types=["resume", "skill", "project", "project_documentation"],
        top_k=8,
        intent="job_fit",
    )
    logger.debug("job_fit_node: retrieved %d chunks", len(chunks))
    return {"context_chunks": chunks}


# ── Relevance grader (LangChain) ─────────────────────────────────────────────

def grade_relevance(question: str, chunks: list, groq_api_key: str = '') -> list:
    """
    Use a LangChain chain (prompt | ChatGroq | JsonOutputParser) to grade each
    retrieved chunk and return only the relevant ones.

    Falls back to returning all chunks if Groq is unavailable or fails.
    """
    if not chunks:
        return chunks
    try:
        from langchain_groq import ChatGroq
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser
        from django.conf import settings as django_settings

        key = groq_api_key or getattr(django_settings, 'GROQ_API_KEY', '')
        if not key:
            return chunks

        llm = ChatGroq(
            api_key=key,
            model='llama-3.1-8b-instant',
            temperature=0,
            max_tokens=10,   # only need {"relevant": true/false}
        )

        prompt = ChatPromptTemplate.from_messages([
            ('system',
             'You are a relevance grader. Given a question and a document excerpt, '
             'respond ONLY with JSON: {{"relevant": true}} or {{"relevant": false}}. '
             'Be generous — mark relevant if the document contains ANY useful info '
             'about the question topic.'),
            ('human', 'Question: {question}\n\nDocument:\n{document}'),
        ])

        chain = prompt | llm | JsonOutputParser()

        relevant = []
        for chunk in chunks:
            try:
                result = chain.invoke({
                    'question': question,
                    'document': chunk['content'][:600],   # cap to save tokens
                })
                if result.get('relevant', True):
                    relevant.append(chunk)
            except Exception:
                relevant.append(chunk)   # on error keep the chunk

        # Always return at least one chunk so generation doesn't get empty context
        return relevant if relevant else chunks[:1]

    except ImportError:
        logger.warning('langchain-groq not installed — skipping relevance grading')
        return chunks
    except Exception as exc:
        logger.warning('relevance grader failed (%s) — returning all chunks', exc)
        return chunks


def relevance_grader_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: filter context_chunks to only relevant ones."""
    question = state.get('question', '')
    chunks   = state.get('context_chunks', [])
    filtered = grade_relevance(question, chunks)
    logger.debug(
        'relevance_grader_node: %d → %d chunks after grading',
        len(chunks), len(filtered),
    )
    return {'context_chunks': filtered}


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
