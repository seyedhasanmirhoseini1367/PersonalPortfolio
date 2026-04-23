import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.1-8b-instant"

# Completely separate from the portfolio RAG chromadb (data/chromadb/)
CHROMA_PATH = str(BASE_DIR / "data" / "content_gen_chromadb")

BRAND_SCORE_THRESHOLD = 0.75
GEO_SCORE_THRESHOLD = 0.75
COMPETITOR_DIFF_THRESHOLD = 0.70
MAX_RETRIES = 3
