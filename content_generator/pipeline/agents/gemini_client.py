import re
import threading
from json_repair import repair_json
from .lc_client import lc_generate


def extract_json(text: str) -> str:
    """Extract and repair JSON from LLM response."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```\s*$", "", text).strip()

    # Find outermost { } by tracking depth
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    return repair_json(candidate)
    return repair_json(text)


MAX_PROMPT_CHARS = 12000  # ~3000 tokens, safe for 6000 TPM limit


def truncate_prompt(prompt: str, limit: int = MAX_PROMPT_CHARS) -> str:
    if len(prompt) <= limit:
        return prompt
    # Keep instruction block (first 2000 chars) + truncated context
    head = prompt[:2000]
    tail = prompt[2000:]
    keep = limit - 2000 - 100
    return head + tail[:keep] + "\n...[content truncated for length]\n" + tail[-200:]


# Model calls made by the current thread's pipeline run (see call_count()).
_calls = threading.local()


def reset_call_count() -> None:
    _calls.n = 0


def call_count() -> int:
    return getattr(_calls, "n", 0)


def generate(prompt: str, retries: int = 5, model: str = None) -> str:
    """Generate via LangChain ChatGroq and extract JSON from the response."""
    _calls.n = call_count() + 1
    prompt = truncate_prompt(prompt)
    raw = lc_generate(prompt, model=model)
    return extract_json(raw)
