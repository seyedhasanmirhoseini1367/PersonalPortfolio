import json
from ..pydantic_models import ContentPiece
from .gemini_client import generate


def optimize_for_geo(content: ContentPiece) -> tuple[ContentPiece, float]:
    """
    Inject GEO signals: statistics, citations, expert quotes, AI-retrievable structure.
    Based on Princeton GEO research (+37-41% AI visibility boost).
    """
    sections_text = json.dumps(content.sections)

    prompt = f"""You are a GEO (Generative Engine Optimization) specialist.
Your goal: make this content get cited by AI engines (ChatGPT, Perplexity, Claude, Google AI Overview).

CURRENT CONTENT:
Title: {content.title}
Headline: {content.headline}
Sections: {sections_text}
CTA: {content.cta}
Language: {content.language}

Apply these GEO techniques — based ONLY on what is already in the content above, do NOT invent sources, companies, or citations:
1. Add specific numbers or statistics that are implied by the content (e.g. "up to 40% faster", "3x more efficient") — only if naturally supported
2. Add a clear definition block: a direct-answer sentence AI engines can lift verbatim
3. Restructure for scannability: short paragraphs, clear headings, direct answers first
4. Make claims concrete and specific (avoid vague adjectives like "great" or "amazing")
5. DO NOT add "(Source: ...)" citations, references, or footnotes — the content must stand on its own brand voice

Return JSON. Keep sections SHORT (2 sentences each max):
- title: (keep or improve)
- headline: (keep or improve)
- sections: enhanced sections with {{"heading": str, "body": str}} — inject GEO signals but stay concise
- cta: (keep)
- language: "{content.language}"
- geo_score: float 0.0-1.0

Return ONLY valid JSON."""

    data = json.loads(generate(prompt))
    geo_score = data.pop("geo_score", 0.8)
    return ContentPiece(**data), geo_score
