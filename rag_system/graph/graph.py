# rag_system/graph/graph.py
"""
Builds and compiles the LangGraph StateGraph for RAG queries.

Flow:
    router_node
        ├── cv       → cv_node
        ├── thesis   → thesis_node
        ├── ml_model → ml_model_node
        ├── projects → projects_node
        └── general  → general_node
                          ↓
                    generate_node
                          ↓
                    verify_node
                     ├── needs_retry=True  → back to original search node
                     └── needs_retry=False → END
"""
import logging

from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import (
    router_node,
    cv_node,
    thesis_node,
    ml_model_node,
    projects_node,
    general_node,
    generate_node,
    verify_node,
)

logger = logging.getLogger(__name__)

# ── Route → node name mapping ─────────────────────────────────────────────────
ROUTE_TO_NODE = {
    "cv":       "cv_node",
    "thesis":   "thesis_node",
    "ml_model": "ml_model_node",
    "projects": "projects_node",
    "general":  "general_node",
}


def _route_from_router(state: AgentState) -> str:
    """Conditional edge: router_node → which search node."""
    return ROUTE_TO_NODE.get(state.get("route", "general"), "general_node")


def _route_from_verify(state: AgentState) -> str:
    """Conditional edge: verify_node → retry search node or END."""
    if state.get("needs_retry", False):
        node = ROUTE_TO_NODE.get(state.get("route", "general"), "general_node")
        logger.debug("verify → retry via %s", node)
        return node
    return END


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("router_node",   router_node)
    graph.add_node("cv_node",       cv_node)
    graph.add_node("thesis_node",   thesis_node)
    graph.add_node("ml_model_node", ml_model_node)
    graph.add_node("projects_node", projects_node)
    graph.add_node("general_node",  general_node)
    graph.add_node("generate_node", generate_node)
    graph.add_node("verify_node",   verify_node)

    # Entry point
    graph.set_entry_point("router_node")

    # router → search nodes (conditional)
    graph.add_conditional_edges(
        "router_node",
        _route_from_router,
        {
            "cv_node":       "cv_node",
            "thesis_node":   "thesis_node",
            "ml_model_node": "ml_model_node",
            "projects_node": "projects_node",
            "general_node":  "general_node",
        },
    )

    # All search nodes → generate
    for node in ["cv_node", "thesis_node", "ml_model_node", "projects_node", "general_node"]:
        graph.add_edge(node, "generate_node")

    # generate → verify
    graph.add_edge("generate_node", "verify_node")

    # verify → retry or END
    graph.add_conditional_edges(
        "verify_node",
        _route_from_verify,
        {
            "cv_node":       "cv_node",
            "thesis_node":   "thesis_node",
            "ml_model_node": "ml_model_node",
            "projects_node": "projects_node",
            "general_node":  "general_node",
            END:             END,
        },
    )

    return graph


# Compiled graph — import this in rag_service.py
rag_graph = build_graph().compile()
