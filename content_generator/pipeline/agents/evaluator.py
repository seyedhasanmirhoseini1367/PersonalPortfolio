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
    checks = {
        # Quantitative data: percentages, decimals, large numbers, fractions
        "has_statistics": bool(re.search(
            r'\d+\.?\d*\s*%'                        # 37%, 4.5%
            r'|\d+\s*(million|billion|thousand)'    # 2 million
            r'|\d+\s*out\s*of\s*\d+'               # 3 out of 4
            r'|\d+x\s*(faster|more|better|cheaper)',# 3x faster
            content, re.I
        )),
        # References to external sources
        "has_citations": bool(re.search(
            r'\(.*?\d{4}.*?\)'                      # (Smith 2023) or (Harvard, 2022)
            r'|\[.*?\]'                             # [1] or [source]
            r'|according to'
            r'|study by|research (by|from|shows|found)'
            r'|report (by|from)|survey (by|from|of)'
            r'|data from|published (by|in)',
            content, re.I
        )),
        # Attributed quote from a named person or expert
        "has_expert_quote": bool(re.search(
            r'["\u201c][^"\u201d]{15,}["\u201d]'   # quoted string 15+ chars
            r'|says\s+[A-Z][a-z]+'                 # says John / says Dr.
            r'|[A-Z][a-z]+\s+[A-Z][a-z]+\s*,'     # "Name Surname," attribution
            r'|(CEO|CTO|founder|director|expert|analyst|professor|researcher)\s+\w+',
            content, re.I
        )),
        # Definitional sentence explaining what something is
        "has_definition_block": bool(re.search(
            r'is defined as'
            r'|refers to'
            r'|means that'
            r'|is the process of'
            r'|can be described as'
            r'|is a (type|form|kind|method|approach|way) of'
            r'|is when\b'
            r'|\bwhat is\b.*?\?'                   # "What is X?" heading
            r'|\bknown as\b',
            content, re.I
        )),
        # Specific numbers tied to real-world entities (not generic)
        "has_unique_data": bool(re.search(
            r'\d+\s*(companies|businesses|firms|clients|customers|users|employees|teams|projects|organisations|organizations)'
            r'|\d+\s*(countries|cities|markets|industries|sectors)'
            r'|\d+\s*(years|months|weeks)\s*(of\s*)?(experience|operation|results)'
            r'|over\s*\d+\s*\w+'                   # "over 200 clients"
            r'|more than\s*\d+\s*\w+',             # "more than 50 companies"
            content, re.I
        )),
    }

    score = sum(checks.values()) * 20  # each check = 20pts

    label_map = {
        "has_statistics": "statistics (percentages / numbers)",
        "has_citations": "citations (sources / references)",
        "has_expert_quote": "expert quote (attributed person or role)",
        "has_definition_block": "definition block (what X is)",
        "has_unique_data": "unique data (specific entities with numbers)",
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


# ── LOOP EVALUATOR (judges 1, 2, 4 — runs each retry) ────────────────────────

def evaluate_loop(content_text: str, audience: str, goal: str) -> dict:
    """Runs inside the retry loop. Judges content quality, GEO signals, and naturalness."""
    print("    [Judge 1] Customer fit...")
    customer = judge_customer(content_text, audience, goal)

    print("    [Judge 2] GEO compliance...")
    geo = judge_geo(content_text)

    print("    [Judge 4] Human naturalness...")
    naturalness = judge_naturalness(content_text)

    overall = round((customer["score"] + geo["score"] + naturalness["score"]) / 3)
    passed = overall >= 70

    return {
        "customer": customer,
        "geo": geo,
        "naturalness": naturalness,
        "overall_score": overall,
        "passed": passed,
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
