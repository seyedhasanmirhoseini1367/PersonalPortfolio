import json
from ..pydantic_models import CompetitorGapMap
from .gemini_client import generate


def analyze_competitors(goal: str, competitor_data: list[str], brand_context: str = "", query_intent: str = "") -> CompetitorGapMap:
    """PRE-FILTER: Analyze competitor content only to find gaps and unique angles.
    If no competitor data provided, LLM infers the top 5 most relevant competitors
    for this specific query intent and finds gaps they miss."""
    if not competitor_data:
        intent_line = f"QUERY INTENT: {query_intent}\n" if query_intent else ""
        prompt = f"""You are a competitive intelligence analyst. No competitor content was provided.
Infer the top 5 most relevant competitors for this specific goal and market.

CONTENT GOAL: {goal}
{intent_line}BRAND CONTEXT: {brand_context or "SME business"}

Identify the 5 most likely competitors a customer would compare against when searching for this.
Then analyze what they typically claim and what they miss.

Return JSON:
{{
  "competitors": ["5 specific competitor names, types, or domains most relevant to this query"],
  "common_claims": ["4-6 generic claims these competitors typically make"],
  "gaps": ["3-5 angles these competitors consistently miss"],
  "unique_angles": ["3-5 specific differentiation angles to own against these competitors"]
}}
Return ONLY valid JSON."""

        data = json.loads(generate(prompt))
        return CompetitorGapMap(**data)

    competitor_context = "\n\n---\n\n".join(competitor_data)

    prompt = f"""You are a competitive intelligence analyst.

COMPETITOR CONTENT:
{competitor_context}

CONTENT GOAL: {goal}

Analyze the competitor content and return JSON with:
- competitors: list of competitor names/domains identified
- common_claims: what competitors say (topics/claims to avoid repeating)
- gaps: topics/angles the competitors completely miss or ignore
- unique_angles: 3-5 specific angles a new entrant can own that competitors don't cover

Return ONLY valid JSON."""

    data = json.loads(generate(prompt))
    return CompetitorGapMap(**data)


def evaluate_differentiation(content: str, gap_map: CompetitorGapMap) -> tuple[float, str]:
    """POST-FILTER: Score how well the content differentiates from competitors."""
    prompt = f"""You are a competitive differentiation evaluator.

COMPETITOR COMMON CLAIMS (content should NOT repeat these):
{', '.join(gap_map.common_claims)}

IDENTIFIED GAPS (content SHOULD cover these):
{', '.join(gap_map.gaps)}

CONTENT TO EVALUATE:
{content}

Score from 0.0 to 1.0 how well this content differentiates from competitors.
Return JSON: {{"score": 0.0-1.0, "feedback": "what overlaps with competitors or what gaps are missed"}}
Return ONLY valid JSON."""

    result = json.loads(generate(prompt))
    return result["score"], result["feedback"]
