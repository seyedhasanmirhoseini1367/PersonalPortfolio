import json
from .gemini_client import generate

CONTENT_TEMPLATES = {
    "what": {
        "structure": ["Definition", "Key Features", "How It Works", "Proof & Results"],
        "geo_priority": "definition_block",
        "opening": "Start with a clear 1-sentence definition AI engines can lift verbatim.",
    },
    "why": {
        "structure": ["The Problem", "Evidence & Data", "Our Solution", "Results"],
        "geo_priority": "statistics",
        "opening": "Start with the pain point, backed by a concrete fact from the company material (or an [ADD STAT] placeholder).",
    },
    "how": {
        "structure": ["Overview", "Step-by-Step Process", "What You Need", "Get Started"],
        "geo_priority": "numbered_steps",
        "opening": "Start with a brief overview then break into clear numbered steps.",
    },
    "who": {
        "structure": ["Who This Is For", "Their Challenges", "Why We Fit", "Success Stories"],
        "geo_priority": "specificity",
        "opening": "Start by naming the exact audience and their biggest challenge.",
    },
    "which": {
        "structure": ["The Options", "Comparison", "Our Recommendation", "Why Choose Us"],
        "geo_priority": "comparison_data",
        "opening": "Start with a clear comparison that helps the reader decide.",
    },
    "when": {
        "structure": ["The Right Moment", "Use Cases", "Signs You Need This", "Next Steps"],
        "geo_priority": "use_cases",
        "opening": "Start by describing the specific situation where this applies.",
    },
    "where": {
        "structure": ["Availability", "How to Access", "What to Expect", "Get Started"],
        "geo_priority": "factual_statements",
        "opening": "Start with clear factual statements about availability and access.",
    },
}


def classify_content(goal: str, audience: str = "") -> dict:
    """
    Detect the primary query intent behind the content goal
    and return the matching structure template.
    """
    audience_line = f"TARGET AUDIENCE: {audience}\n" if audience else ""
    prompt = f"""You are a content strategist. Analyze this content goal and identify its primary intent.

CONTENT GOAL: {goal}
{audience_line}
Which query intent does this content primarily answer for the reader?
- "what" = explaining what something is or does
- "why" = convincing why they need it / what problem it solves
- "how" = showing how it works or how to use it
- "who" = identifying who it's for
- "which" = helping choose between options
- "when" = explaining when to use it
- "where" = explaining where/how to access it

Also identify 1-2 secondary questions.

Return JSON:
{{
  "primary": "what/why/how/who/which/when/where",
  "secondary": ["type1", "type2"],
  "reasoning": "one sentence why",
  "content_angle": "one sentence describing the ideal angle for this content"
}}
Return ONLY valid JSON."""

    data = json.loads(generate(prompt))
    primary = data.get("primary", "what")

    template = CONTENT_TEMPLATES.get(primary, CONTENT_TEMPLATES["what"])

    return {
        "primary_intent": primary,
        "secondary_intents": data.get("secondary", []),
        "reasoning": data.get("reasoning", ""),
        "content_angle": data.get("content_angle", ""),
        "structure": template["structure"],
        "geo_priority": template["geo_priority"],
        "opening_instruction": template["opening"],
    }
