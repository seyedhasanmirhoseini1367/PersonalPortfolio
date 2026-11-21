import json
from ..pydantic_models import ContentPiece
from .gemini_client import generate


def optimize_for_geo(content: ContentPiece) -> tuple[ContentPiece, float]:
    """
    Improve structure and clarity for AI engines without adding any new facts.
    (Statistics/quotes are only kept when the writer already took them from the sources.)
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

Apply these GEO techniques using ONLY what is already in the content above:
1. Add a clear definition block: a direct-answer sentence AI engines can lift verbatim
2. Restructure for scannability: short paragraphs, clear headings, direct answers first
3. Make wording concrete (say what the product does) instead of vague adjectives like "great"
4. NEVER add a number, percentage, statistic, study, survey, quote, customer name, award or
   "(Source: ...)" that is not already in the content. Keep every [ADD STAT] placeholder exactly as it is.

Return JSON. Keep sections SHORT (2 sentences each max):
- title: (keep or improve)
- headline: (keep or improve)
- sections: enhanced sections with {{"heading": str, "body": str}} — clearer, same facts, concise
- cta: (keep)
- language: "{content.language}"
- geo_score: float 0.0-1.0

Return ONLY valid JSON."""

    data = json.loads(generate(prompt))
    geo_score = data.pop("geo_score", 0.8)
    return ContentPiece(**data), geo_score
