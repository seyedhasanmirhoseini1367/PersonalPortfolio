import json
from ..pydantic_models import BrandProfile
from .ingestion import query_collection
from .gemini_client import generate


def analyze_brand(client_id: str, scope_ids: list[str] = None) -> BrandProfile:
    """PRE-FILTER: Build BrandProfile from client's own data via RAG."""
    queries = [
        "company values and mission",
        "tone of voice and writing style",
        "target audience and customers",
        "unique differentiators and positioning",
    ]

    retrieved = []
    seen = set()
    for q in queries:
        chunks = query_collection(client_id, q, n_results=2, scope_ids=scope_ids)
        for c in chunks:
            if c not in seen:
                seen.add(c)
                retrieved.append(c)

    # Cap context at ~2000 chars to stay within token limits
    context = "\n\n".join(retrieved)
    context = context[:2000]

    prompt = f"""You are a brand strategist. Analyze the following company content and extract a structured brand profile.

COMPANY CONTENT:
{context}

Return a JSON object with exactly these fields:
- tone: how they write (e.g. "conversational and warm", "formal and authoritative")
- values: list of 3-5 core brand values
- audience: description of their primary target audience
- preferred_style: sentence structure, vocabulary, formatting preferences
- forbidden_words: list of words/phrases that don't fit their brand
- differentiators: list of what makes them unique vs competitors

Return ONLY valid JSON, no explanation."""

    data = json.loads(generate(prompt))
    return BrandProfile(**data)


def evaluate_brand_alignment(content: str, brand: BrandProfile) -> tuple[float, str]:
    """POST-FILTER: Score how well the content matches the brand profile."""
    prompt = f"""You are a brand alignment evaluator.

BRAND PROFILE:
- Tone: {brand.tone}
- Values: {', '.join(brand.values)}
- Audience: {brand.audience}
- Preferred style: {brand.preferred_style}
- Forbidden words: {', '.join(brand.forbidden_words)}

CONTENT TO EVALUATE:
{content}

Score this content from 0.0 to 1.0 on brand alignment.
Return JSON: {{"score": 0.0-1.0, "feedback": "specific issues or confirmation"}}
Return ONLY valid JSON."""

    result = json.loads(generate(prompt))
    return result["score"], result["feedback"]
