import json
from ..pydantic_models import ContentPiece, BrandProfile
from .ingestion import query_collection
from .gemini_client import generate

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

    prompt = f"""You are a professional content localizer specializing in brand-aligned translation.

TARGET LANGUAGE: {target_language}
CULTURAL CONTEXT: {cultural_note}

BRAND VOICE: {brand.tone}
BRAND VALUES: {', '.join(brand.values)}

EXISTING CLIENT CONTENT IN {target_language} (match this voice):
{existing_local_content}

CONTENT TO LOCALIZE:
Title: {content.title}
Headline: {content.headline}
Sections: {sections_text}
CTA: {content.cta}

Rules:
- This is LOCALIZATION not just translation — adapt culturally
- Preserve all GEO signals (statistics, citations, expert quotes)
- Preserve brand voice in the target language
- Preserve meaning and key messages

Return JSON:
- title: localized
- headline: localized
- sections: list of {{"heading": str, "body": str}} — fully localized
- cta: localized
- language: "{target_language}"

Return ONLY valid JSON."""

    data = json.loads(generate(prompt))
    # unwrap if LLM nested the response
    for key in ("content", "localized", "result", "translation"):
        if key in data and isinstance(data[key], dict):
            data = data[key]
            break
    data.setdefault("cta", content.cta)
    data.setdefault("language", target_language)
    return ContentPiece(**data)
