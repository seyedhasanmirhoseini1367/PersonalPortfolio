import numpy as np
from .ingestion import _model

ALL_SCOPE_KEYWORDS = {"all", "everything", "whole", "entire", "general", "company", "overall", "every"}


def detect_scope(goal: str, scopes: list[tuple[str, str]]) -> list[str]:
    """
    Detect which scope(s) the goal is targeting.

    Args:
        goal: the user's content goal
        scopes: list of (scope_id, scope_name) for this company

    Returns:
        list of matching scope_ids, or [] meaning use all scopes
    """
    if not scopes:
        return []

    # If goal explicitly says "everything" / "all" / "company" → use all scopes
    goal_words = set(goal.lower().split())
    if goal_words & ALL_SCOPE_KEYWORDS:
        return []

    # Semantic matching: embed goal vs all scope names
    goal_emb = _model.encode([goal], convert_to_numpy=True)[0]
    scope_names = [name for _, name in scopes]
    scope_embs = _model.encode(scope_names, convert_to_numpy=True)

    # Cosine similarity
    goal_norm = goal_emb / (np.linalg.norm(goal_emb) + 1e-8)
    scope_norms = scope_embs / (np.linalg.norm(scope_embs, axis=1, keepdims=True) + 1e-8)
    similarities = scope_norms @ goal_norm

    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])

    # Threshold: if similarity is strong enough, return that scope
    if best_score >= 0.35:
        print(f"  Scope detected: '{scope_names[best_idx]}' (score: {best_score:.2f})")
        return [scopes[best_idx][0]]

    # No confident match → use all
    print(f"  No specific scope matched (best: '{scope_names[best_idx]}' @ {best_score:.2f}) — using all data")
    return []
