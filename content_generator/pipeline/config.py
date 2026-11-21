import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

try:  # local development: read .env (production sets real environment variables)
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Providers retire models often: override with GEMINI_MODEL / GROQ_MODEL / GROQ_MODEL_LARGE.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_MODEL_LARGE = os.getenv("GROQ_MODEL_LARGE", "openai/gpt-oss-120b")

BRAND_SCORE_THRESHOLD = 0.75
GEO_SCORE_THRESHOLD = 0.75
COMPETITOR_DIFF_THRESHOLD = 0.70
MAX_RETRIES = 3
