import json
from ..pydantic_models import BrandProfile, ContentBrief, CompetitorGapMap, ContentPiece, ImageAsset, VideoAsset
from .ingestion import query_collection
from .gemini_client import generate
from .grounding import GROUNDING_RULES


def build_content_brief(
    goal: str,
    brand: BrandProfile,
    gap_map: CompetitorGapMap,
    seo_params: dict = None,
) -> ContentBrief:
    prompt = f"""You are a content strategist.

GOAL: {goal}
BRAND AUDIENCE: {brand.audience}
BRAND VALUES: {', '.join(brand.values)}
UNIQUE ANGLES AVAILABLE: {', '.join(gap_map.unique_angles)}
GAPS TO FILL: {', '.join(gap_map.gaps)}

Build a content brief as JSON:
- goal: restate the goal clearly
- angle: the single best angle to take (from unique angles)
- target_audience: specific description (one sentence)
- key_messages: list of 3 short messages
- gap_opportunities: list of 2-3 gaps this content will fill

Key messages must not contain numbers, results, awards or claims that are not stated above.

Return ONLY valid JSON."""

    data = json.loads(generate(prompt))
    if "content_brief" in data:
        data = data["content_brief"]
    # Merge in user-specified SEO/GEO controls (not LLM-generated)
    if seo_params:
        data.update({k: v for k, v in seo_params.items() if v is not None})
    return ContentBrief(**data)


# Formats with word-count / section / data-point controls; the rest have fixed shapes.
LONG_FORMATS = {"blog_post", "landing_page"}


def _content_json(raw: str):
    """Parsed content dict, or None when the reply is not usable content."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(data, list):   # LLM sometimes wraps response in [...]
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return None
    for wrapper in ("content", "output", "result"):
        if "title" not in data and isinstance(data.get(wrapper), dict):
            data = data[wrapper]
    if not str(data.get("title", "")).strip() and not str(data.get("headline", "")).strip():
        return None
    data.setdefault("title", data.get("headline", ""))
    return data


FORMAT_PROMPTS = {
    "motto": {
        "role": "brand copywriter",
        "task": "Write ONE single brand tagline — a short, punchy phrase of 3–8 words. Nothing else.",
        "rules": "title = 'Tagline'. headline = the tagline (3–8 words, memorable, no full sentences). sections = [] — THIS MUST BE AN EMPTY LIST, DO NOT add any sections, body text, or explanations. cta = '' (empty string). OUTPUT ONLY the JSON, no paragraphs, no descriptions.",
    },
    "social_post": {
        "role": "social media copywriter",
        "task": "Write a LinkedIn-style social media post.",
        "rules": "title = 'Social Post'. headline = '' (empty string). sections = exactly 1 item: heading='Post', body=the full post text (max 120 words, conversational tone, no hashtags in body). cta = 2-3 relevant hashtags as a single string. OUTPUT ONLY the JSON.",
    },
    "blog_post": {
        "role": "blog writer",
        "task": "Write a full blog post.",
        "rules": "headline = blog H1 title. sections = exactly 5 items: Introduction, then 3 body sections, then Conclusion. Each body section 3-4 sentences. cta = 'Subscribe' or 'Read more'. title = SEO blog title.",
    },
    "landing_page": {
        "role": "website copywriter",
        "task": "Write a concise landing page.",
        "rules": "headline = punchy H1. sections = exactly 3 items following the content structure. Each section body 2 sentences max. cta = action button text (5 words max). title = SEO title (60 chars max).",
    },
    "email": {
        "role": "email marketing copywriter",
        "task": "Write a marketing email.",
        "rules": "title = the email subject line (compelling, max 60 chars). headline = same subject line. sections = exactly 3 items: heading='Opening' (warm intro, 2 sentences), heading='Main Message' (value prop, 3 sentences), heading='Closing' (urgency/next step, 2 sentences). cta = email button text (5 words max).",
    },
    "ad_copy": {
        "role": "advertising copywriter",
        "task": "Write 3 short ad copy variations.",
        "rules": "headline = primary campaign headline. sections = exactly 3 items, each an ad variation: heading='Ad 1/2/3', body=ad text (max 25 words each, punchy and direct). cta = shared call-to-action (5 words max). title = 'Ad Campaign'.",
    },
}


TONE_INSTRUCTIONS = {
    "professional": "Authoritative, clear, confident. Formal vocabulary, precise language.",
    "casual":       "Friendly, conversational, warm. Short sentences, contractions OK.",
    "bold":         "Direct, provocative, high-energy. Strong verbs, punchy statements.",
    "empathetic":   "Understanding, supportive, human. Address pain points with compassion.",
    "technical":    "Precise, data-driven, expert-level. Technical terms welcome, no fluff.",
}


_READING_LEVEL_DESCS = {
    "Simple":       "use simple everyday language, short sentences (8-12 words), avoid all jargon",
    "Professional": "clear polished professional tone — accessible but not simplistic, no buzzwords",
    "Technical":    "expert vocabulary, technical depth, precise terminology welcome",
}


def write_content(
    client_id: str,
    brief: ContentBrief,
    brand: BrandProfile,
    content_type: dict,
    language: str = "English",
    feedback: str = None,
    content_format: str = "landing_page",
    scope_ids: list[str] = None,
    keywords: list[str] = None,
    previous_outputs: list[dict] = None,
    tone_preset: str = "professional",
    seo_controls: dict = None,
) -> ContentPiece:
    rag_chunks = query_collection(client_id, brief.goal, n_results=4, scope_ids=scope_ids)
    rag_context = "\n\n".join(rag_chunks)
    feedback_block = f"\nPREVIOUS FEEDBACK:\n{feedback}" if feedback else ""
    keywords_block = (
        f"\n⚠ MANDATORY KEYWORDS — you MUST include EVERY one of these in the output, verbatim, at least once:\n"
        + "\n".join(f"  - {k}" for k in keywords)
        + "\nDo NOT skip any. If a keyword does not fit naturally, force it into a heading or CTA."
    ) if keywords else ""

    tone_desc = TONE_INSTRUCTIONS.get(tone_preset, TONE_INSTRUCTIONS["professional"])
    tone_block = f"\nTONE PRESET — {tone_preset.upper()}: {tone_desc}"

    if previous_outputs:
        lines = "\n".join(
            f"  - [{p.get('content_format','').upper()}] \"{p.get('title','')}\" — angle: {p.get('angle','')}"
            for p in previous_outputs
        )
        history_block = f"\nALREADY GENERATED (do NOT repeat these angles, titles, or structures — create something fresh):\n{lines}"
    else:
        history_block = ""

    # ── SEO/GEO structural constraints block ──────────────────────────────────
    sc = seo_controls or {}
    word_min     = sc.get('word_count_min', 600)
    word_max     = sc.get('word_count_max', 1200)
    h2_count     = sc.get('h2_count', 3)
    stats_req    = sc.get('stats_required', 2)
    faq_count    = sc.get('faq_count', 0)
    level        = sc.get('reading_level', 'Professional')
    angle        = sc.get('content_angle', '')
    cta_override = sc.get('cta_override', '')

    level_desc  = _READING_LEVEL_DESCS.get(level, _READING_LEVEL_DESCS["Professional"])
    faq_line    = (f"- FAQ section: add a section with heading='FAQ' containing exactly "
                   f"{faq_count} Q&A pairs in the body\n") if faq_count > 0 else ""
    angle_line  = f"- Content angle: frame the entire piece as a {angle}\n" if angle else ""
    cta_line    = f"- CTA text: use exactly this CTA string: \"{cta_override}\"\n" if cta_override else ""

    if content_format in LONG_FORMATS:
        seo_block = (
            f"\n⚠ HARD STRUCTURAL CONSTRAINTS — FOLLOW EXACTLY:\n"
            f"- Word count: write {word_min}–{word_max} words total across all sections combined\n"
            f"- H2 sections: create exactly {h2_count} items in the sections array\n"
            f"- Figures: include up to {stats_req} concrete data points ONLY if they appear in COMPANY FACTS; "
            f"for any missing ones write the placeholder [ADD STAT] (never invent a number)\n"
            f"{faq_line}"
            f"{angle_line}"
            f"{cta_line}"
            f"- Reading level: {level} — {level_desc}"
        )
    else:
        # Short formats (tagline, post, ad, email): their FORMAT RULES fix the
        # length and structure. Long-form limits here contradicted them, and
        # the model answered with an error object instead of content.
        seo_block = f"\n{angle_line}{cta_line}- Reading level: {level} — {level_desc}"

    fmt = FORMAT_PROMPTS.get(content_format, FORMAT_PROMPTS["landing_page"])
    structure = " → ".join(content_type["structure"])

    prompt = f"""You are a {fmt['role']}. {fmt['task']}

FORMAT RULES: {fmt['rules']}
{tone_block}
{seo_block}
{keywords_block}
{history_block}
BRAND VOICE: {brand.tone}
FORBIDDEN WORDS: {', '.join(brand.forbidden_words)}
TARGET AUDIENCE: {brief.target_audience}
CONTENT ANGLE: {brief.angle}
KEY MESSAGES: {', '.join(brief.key_messages)}
LANGUAGE: {language}
CONTENT STRUCTURE HINT: {structure}

{GROUNDING_RULES}

COMPANY FACTS (the only source of facts; also match this voice):
{rag_context or "(no company material provided — make no factual claims beyond the goal and keywords)"}
{feedback_block}

Return JSON with these exact keys:
- title (string)
- headline (string)
- sections (list of objects with "heading" and "body")
- cta (string)
- language (string, value: "{language}")
- seo_title (string, 50-60 chars, keyword-rich meta title)
- seo_description (string, 120-160 chars, compelling meta description with primary keyword)

If any instructions seem to conflict, follow FORMAT RULES and FACTS RULES and still write the content.
Never return an error, a refusal or anything other than this JSON object.
Return ONLY valid JSON."""

    data = _content_json(generate(prompt))
    if data is None:
        # The model answered with something other than content (e.g. an
        # {"errors": [...]} object); ask once more, then give a clear error.
        data = _content_json(generate(prompt + "\n\nYour previous reply was not the content JSON. "
                                      "Write the content now as the JSON object described above."))
    if data is None:
        raise ValueError("The AI model did not return any content for this format. Please try again.")
    piece = ContentPiece(**data)
    if cta_override:
        piece.cta = cta_override

    # Verify all keywords are present; retry once with stricter instruction if any missing
    if keywords:
        full_text = json.dumps(data).lower()
        missing = [k for k in keywords if k.lower() not in full_text]
        if missing:
            retry_prompt = prompt + f"""

RETRY INSTRUCTION: The previous output was REJECTED because these keywords were missing:
{', '.join(missing)}

You MUST include every missing keyword verbatim in the output. Rewrite and return ONLY valid JSON."""
            retried = _content_json(generate(retry_prompt))
            if retried is not None:   # keep the first version if the retry is unusable
                piece = ContentPiece(**retried)
                if cta_override:
                    piece.cta = cta_override

    # Generate image/video prompts for formats that benefit from visuals
    if content_format not in ('motto',):
        piece.image_prompts = _suggest_image_prompts(piece, brand, content_format)
    if content_format in ('landing_page', 'blog_post', 'social_post'):
        piece.video_prompts = _suggest_video_prompts(piece, brand, content_format)

    return piece


def _suggest_image_prompts(piece: ContentPiece, brand: BrandProfile, content_format: str) -> list[ImageAsset]:
    """Ask the LLM to suggest image generation prompts for the content."""
    n = {"blog_post": 3, "landing_page": 2, "social_post": 1, "email": 1, "ad_copy": 3}.get(content_format, 1)
    prompt = f"""You are a visual art director. Based on this content, suggest {n} image(s) that would pair with it.

CONTENT TITLE: {piece.title}
HEADLINE: {piece.headline}
BRAND TONE: {brand.tone}
AUDIENCE: {brand.audience}

Return a JSON array of {n} objects, each with:
- "prompt": a detailed DALL-E/Stable Diffusion generation prompt (describe style, subject, mood, colors)
- "alt_text": short accessible description (10 words max)

Return ONLY the JSON array."""
    try:
        items = json.loads(generate(prompt))
        if isinstance(items, dict):
            items = [items]
        return [ImageAsset(**i) for i in items[:n]]
    except Exception:
        return []


def _suggest_video_prompts(piece: ContentPiece, brand: BrandProfile, content_format: str) -> list[VideoAsset]:
    """Ask the LLM to suggest a short video concept for the content."""
    prompt = f"""You are a video creative director. Suggest 1 short video concept for this content.

CONTENT TITLE: {piece.title}
BRAND TONE: {brand.tone}
FORMAT: {content_format}

Return a JSON object with:
- "prompt": a Runway/Kling video generation prompt (describe scene, motion, mood, duration)
- "duration_seconds": suggested clip length (5–30)

Return ONLY the JSON object."""
    try:
        item = json.loads(generate(prompt))
        return [VideoAsset(**item)]
    except Exception:
        return []
