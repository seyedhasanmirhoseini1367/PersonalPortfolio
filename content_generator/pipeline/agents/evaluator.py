import json
import re
from .gemini_client import generate

AI_CLICHES = [
    "delve", "revolutionize", "transformative", "leverage", "synergy",
    "cutting-edge", "game-changer", "seamless", "robust", "scalable",
    "empower", "unlock", "harness", "crucial", "utilize", "facilitate",
    "in conclusion", "it is worth noting", "it is important to note",
]


# ── JUDGE 1: CUSTOMER FIT ────────────────────────────────────────────────────

def judge_customer(content: str, audience: str, goal: str) -> dict:
    prompt = f"""You are evaluating marketing content from the perspective of the TARGET CUSTOMER.

TARGET AUDIENCE: {audience}
CONTENT GOAL: {goal}

CONTENT:
{content}

Score 0-100 on how well this content serves the customer:
- Does it address their real pain points?
- Is the language appropriate for their level (not too technical, not too simple)?
- Does it answer questions they would ask an AI engine?
- Is there a clear value proposition for them?
- Does it have a compelling call to action?

Return JSON:
{{
  "score": 0-100,
  "pain_points_addressed": true/false,
  "clarity": "excellent/good/poor",
  "value_proposition": "clear/vague/missing",
  "feedback": "2-3 specific sentences on what works and what to improve"
}}
Return ONLY valid JSON."""

    data = json.loads(generate(prompt))
    return {
        "score": int(data.get("score", 70)),
        "pain_points_addressed": data.get("pain_points_addressed", True),
        "clarity": data.get("clarity", "good"),
        "value_proposition": data.get("value_proposition", "clear"),
        "feedback": data.get("feedback", ""),
    }


# ── JUDGE 2: GEO COMPLIANCE (checklist — objective) ──────────────────────────

def judge_geo(content: str) -> dict:
    """Structure and clarity signals that do not require inventing facts.

    Statistics, citations and expert quotes used to be scored here, which
    pushed the writer (through the retry feedback) to make them up. Figures
    now count when present OR when the writer left an [ADD STAT] placeholder,
    and unsourced attributions lower the score instead of raising it.
    """
    from .grounding import ATTRIBUTION_RE, PLACEHOLDER

    blocks = [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]
    # Headings: short lines that do not end like a sentence
    headings = [p for p in blocks if len(p.split()) <= 12 and not p.endswith(('.', '!'))]
    paragraphs = [p for p in blocks if p not in headings]
    avg_words = (sum(len(p.split()) for p in paragraphs) / len(paragraphs)) if paragraphs else 0
    checks = {
        # A sentence that defines or directly answers (AI engines lift these verbatim)
        "has_definition_block": bool(re.search(
            r'is defined as|refers to|means that|is the process of|can be described as'
            r'|is an? (type|form|kind|method|approach|way|tool|app|service|platform) (of|for|that)'
            r'|is when\b|\bwhat is\b.*?\?|\bknown as\b|\bhelps\b', content, re.I)),
        # Concrete figures — from the sources, or a placeholder for a human to fill
        "has_concrete_facts": bool(re.search(r'\d', content)) or PLACEHOLDER in content,
        # Headings phrased as the questions people ask
        "has_question_headings": any(h.strip().endswith('?') or re.match(r'(what|how|why|who|when|which)\b', h.strip(), re.I)
                                     for h in headings),
        # Short, scannable paragraphs
        "has_short_paragraphs": 0 < avg_words <= 90,
        # No "studies show" / "according to" without a real source
        "no_unsourced_claims": not ATTRIBUTION_RE.search(content),
    }

    score = sum(checks.values()) * 20  # each check = 20pts

    label_map = {
        "has_definition_block": "definition / direct-answer sentence (what it is, who it helps)",
        "has_concrete_facts": "concrete facts (use figures from the company material, or an [ADD STAT] placeholder — never invent)",
        "has_question_headings": "question-style headings (What / How / Why ...)",
        "has_short_paragraphs": "short paragraphs (under ~90 words)",
        "no_unsourced_claims": "remove 'studies show' / 'according to' claims that have no real source",
    }
    missing = [label_map[k] for k, v in checks.items() if not v]

    return {
        "score": score,
        "checks": checks,
        "missing": missing,
        "feedback": f"Missing GEO signals: {', '.join(missing)}" if missing else "All GEO signals present.",
    }


# ── JUDGE 3: COMPETITOR EDGE ─────────────────────────────────────────────────

def judge_competitor(content: str, competitor_data: list[str], gap_map_gaps: list[str]) -> dict:
    if not competitor_data:
        return {
            "score": 75,
            "beats_on_specificity": True,
            "covers_gaps": True,
            "unique_angle": True,
            "feedback": "No competitor data provided — score based on content quality alone.",
        }

    competitor_context = "\n\n---\n\n".join(competitor_data[:3])

    prompt = f"""You are comparing marketing content against competitor content.

OUR CONTENT:
{content}

COMPETITOR CONTENT:
{competitor_context}

GAPS OUR CONTENT SHOULD FILL:
{', '.join(gap_map_gaps)}

Score 0-100 on competitive advantage:
- Is our content more specific and data-rich than competitors?
- Does it cover gaps that competitors miss?
- Would a customer choose our content over competitors?
- Does it have a clearly differentiated angle?

Return JSON:
{{
  "score": 0-100,
  "beats_on_specificity": true/false,
  "covers_gaps": true/false,
  "unique_angle": true/false,
  "feedback": "2-3 specific sentences comparing our content vs competitors"
}}
Return ONLY valid JSON."""

    data = json.loads(generate(prompt))
    return {
        "score": int(data.get("score", 70)),
        "beats_on_specificity": data.get("beats_on_specificity", True),
        "covers_gaps": data.get("covers_gaps", True),
        "unique_angle": data.get("unique_angle", True),
        "feedback": data.get("feedback", ""),
    }


# ── JUDGE 4: HUMAN NATURALNESS ───────────────────────────────────────────────

def judge_naturalness(content: str) -> dict:
    found_cliches = [w for w in AI_CLICHES if w.lower() in content.lower()]

    prompt = f"""You are evaluating marketing content for naturalness and readability.

CONTENT:
{content}

Score 0-100 on how natural and human this reads as MARKETING COPY (not literature):
- 90-100 = reads like a skilled copywriter wrote it
- 70-89 = good marketing copy, minor formulaic phrases
- 50-69 = decent but some AI patterns present
- 30-49 = clearly templated/formulaic
- 0-29 = robotic

Note: Marketing content is allowed to be structured and professional.
Penalize only: overused buzzwords, repetitive sentence structure, no specific details.

Return JSON:
{{
  "score": 0-100,
  "sounds_human": true/false,
  "ai_patterns_detected": ["list specific patterns found, if any"],
  "feedback": "2 sentences on what to improve"
}}
Return ONLY valid JSON."""

    data = json.loads(generate(prompt))

    score = int(data.get("score", 70))
    if found_cliches:
        score = max(0, score - len(found_cliches) * 3)

    return {
        "score": score,
        "sounds_human": data.get("sounds_human", True),
        "ai_cliches_found": found_cliches,
        "ai_patterns": data.get("ai_patterns_detected", []),
        "feedback": data.get("feedback", ""),
    }


# ── JUDGE 5: STRUCTURAL VALIDATION ───────────────────────────────────────────

def judge_structure(content_text: str, content_piece, seo_params: dict) -> dict:
    """Verify word count, section count, and FAQ presence against user-specified controls."""
    words        = len(content_text.split())
    word_min     = seo_params.get('word_count_min', 600)
    word_max     = seo_params.get('word_count_max', 1200)
    h2_expected  = seo_params.get('h2_count', 3)
    faq_expected = seo_params.get('faq_count', 0)

    sections      = getattr(content_piece, 'sections', []) or []
    section_count = len(sections)

    issues = []
    if words < word_min:
        issues.append(f"Too short: ~{words} words (minimum {word_min})")
    elif words > word_max * 1.25:  # allow 25% overrun before flagging
        issues.append(f"Too long: ~{words} words (maximum {word_max})")

    if section_count < h2_expected:
        issues.append(f"Needs {h2_expected} H2 sections, has {section_count}")

    if faq_expected > 0:
        has_faq = any(
            'faq' in str(s.get('heading', '')).lower()
            or 'frequently' in str(s.get('heading', '')).lower()
            or 'question' in str(s.get('heading', '')).lower()
            for s in sections
        )
        if not has_faq:
            issues.append(f"Missing FAQ section ({faq_expected} Q&A pairs required)")

    score = max(0, 100 - len(issues) * 30)
    return {
        'score':         score,
        'word_count':    words,
        'section_count': section_count,
        'issues':        issues,
        'feedback':      ('; '.join(issues) if issues
                          else f"Structure OK: ~{words} words, {section_count} sections"),
    }


# ── LOOP EVALUATOR (judges 1, 2, 4 — runs each retry) ────────────────────────

def evaluate_loop(
    content_text: str,
    audience: str,
    goal: str,
    content_piece=None,
    seo_params: dict = None,
) -> dict:
    """Runs inside the retry loop. Judges content quality, GEO signals, and naturalness."""
    print("    [Judge 1] Customer fit...")
    customer = judge_customer(content_text, audience, goal)

    print("    [Judge 2] GEO compliance...")
    geo = judge_geo(content_text)

    print("    [Judge 4] Human naturalness...")
    naturalness = judge_naturalness(content_text)

    structure_issues   = []
    structure_feedback = ""
    if content_piece is not None and seo_params:
        print("    [Judge 5] Structure validation...")
        structure        = judge_structure(content_text, content_piece, seo_params)
        structure_issues = structure["issues"]
        structure_feedback = structure["feedback"] if structure_issues else ""

    overall = round((customer["score"] + geo["score"] + naturalness["score"]) / 3)
    passed  = overall >= 70 and not structure_issues

    return {
        "customer":          customer,
        "geo":               geo,
        "naturalness":       naturalness,
        "overall_score":     overall,
        "passed":            passed,
        "structure_issues":  structure_issues,
        "structure_feedback": structure_feedback,
    }


# ── POST-LOOP COMPETITOR EDGE (judge 3 — runs once after loop) ────────────────

def evaluate_competitor_edge(
    content_text: str,
    competitor_data: list[str],
    gap_map_gaps: list[str],
) -> dict:
    """Runs once after the loop. Compares final content against competitors."""
    print("    [Judge 3] Competitor edge...")
    return judge_competitor(content_text, competitor_data, gap_map_gaps)
