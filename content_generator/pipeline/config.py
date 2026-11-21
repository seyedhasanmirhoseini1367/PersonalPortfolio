import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Groq retires models often: override with GROQ_MODEL / GROQ_MODEL_LARGE.
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_MODEL_LARGE = os.getenv("GROQ_MODEL_LARGE", "openai/gpt-oss-120b")

BRAND_SCORE_THRESHOLD = 0.75
GEO_SCORE_THRESHOLD = 0.75
COMPETITOR_DIFF_THRESHOLD = 0.70
MAX_RETRIES = 3
