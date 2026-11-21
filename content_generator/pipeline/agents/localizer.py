import json
from ..pydantic_models import ContentPiece, BrandProfile
from .ingestion import query_collection
from .gemini_client import generate
from ..config import GROQ_MODEL_LARGE

LANGUAGE_CONTEXT = {
    "Finnish": "Finnish business culture values directness, modesty, and practicality. Avoid hype. Use 'sinä' form for direct audience address.",
    "Swedish": "Swedish business culture values clarity, equality, and innovation. Tone is friendly but professional.",
    "German": "German business culture values precision, expertise, and reliability. Be thorough and specific.",
}


def localize_content(
    client_id: str,
    content: ContentPiece,
    target_language: str,
    brand: BrandProfile
) -> ContentPiece:
    """Localize content to target language with cultural adaptation."""
    rag_chunks = query_collection(client_id, f"{target_language} content examples", n_results=3)
    existing_local_content = "\n\n".join(rag_chunks) if rag_chunks else "No existing content found."
    cultural_note = LANGUAGE_CONTEXT.get(target_language, "")
    sections_text = json.dumps(content.sections)

    prompt = f"""You are a professional translator and content localizer.

⚠ YOUR ONLY TASK: Translate and culturally adapt the EXACT content provided below into {target_language}.
DO NOT generate new content. DO NOT add new sections. DO NOT change the structure.
If sections is an empty list, return an empty list for sections.

TARGET LANGUAGE: {target_language}
CULTURAL CONTEXT: {cultural_note}

BRAND VOICE: {brand.tone}

CONTENT TO TRANSLATE (translate every field, keep structure identical):
Title: {content.title}
Headline: {content.headline}
Sections: {sections_text}
CTA: {content.cta}

Return a single JSON object with these exact keys:
- "title": translated title string
- "headline": translated headline string
- "sections": translated list (same length and structure as input — if input is [], return [])
- "cta": translated CTA string
- "language": "{target_language}"

Return ONLY valid JSON. No explanation. No extra keys."""

    data = json.loads(generate(prompt, model=GROQ_MODEL_LARGE))
    if isinstance(data, list):
        data = data[0] if data else {}
    # unwrap if LLM nested the response
    for key in ("content", "localized", "result", "translation"):
        if key in data and isinstance(data[key], dict):
            data = data[key]
            break
    data.setdefault("cta", content.cta)
    data.setdefault("language", target_language)
    return ContentPiece(**data)
