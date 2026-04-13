# rag_system/graph/state.py
"""
AgentState — shared state object passed between every LangGraph node.
Each node receives a copy, updates relevant fields, and returns the updated dict.
"""
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict):
    # Core
    question:    str
    route:       str          # "cv" | "thesis" | "ml_model" | "projects" | "general"
    answer:      str

    # Retrieval
    context_chunks: List[Dict[str, Any]]

    # Session / history
    session_id: Optional[str]
    history:    List[Dict[str, str]]   # [{"role": "user"|"assistant", "content": "..."}]

    # ML model route extras
    ml_prediction: Optional[Dict[str, Any]]

    # Self-correction
    needs_retry: bool
    retry_count: int
