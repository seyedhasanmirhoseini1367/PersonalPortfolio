from .ingestion import tokenize

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

    # Word overlap between the goal and each scope name (share of the
    # scope name's words that appear in the goal).
    goal_tokens = set(tokenize(goal))
    best_idx, best_score = 0, 0.0
    for i, (_, name) in enumerate(scopes):
        name_tokens = set(tokenize(name))
        if not name_tokens:
            continue
        score = len(goal_tokens & name_tokens) / len(name_tokens)
        if score > best_score:
            best_idx, best_score = i, score

    if best_score >= 0.5:
        return [scopes[best_idx][0]]
    return []
