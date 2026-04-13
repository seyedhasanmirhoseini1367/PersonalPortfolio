# Hasan Mirhoseini — AI Portfolio

A personal portfolio for a Data Scientist and ML Engineer, built with Django. Features a fully integrated RAG-powered AI assistant that answers questions about projects, skills, and resume — automatically kept in sync with the admin.

---

## RAG System

The RAG (Retrieval-Augmented Generation) system is the core AI feature of this portfolio. It lets visitors ask natural language questions like *"What machine learning projects has Hasan worked on?"* or *"What is his thesis about?"* and get accurate, context-aware answers drawn directly from portfolio content.

### Architecture

```
User Question
     │
     ▼
┌─────────────┐
│ Router Node │  ← keyword-based, free (no LLM call)
└──────┬──────┘
       │  routes to one of:
   ┌───┴────────────────────────────────┐
   ▼       ▼         ▼         ▼        ▼
cv_node  thesis_  ml_model  projects  general
         node     _node     _node     _node
   └───────────────────┬────────────────┘
                       ▼
               ┌───────────────┐
               │ generate_node │  ← Gemini / Anthropic / OpenAI
               └───────┬───────┘
                       ▼
               ┌───────────────┐
               │  verify_node  │  ← checks answer quality
               └───────┬───────┘
              good ◄───┤───► needs_retry → back to search node
                       ▼
                      END
```

Built with **LangGraph** (`StateGraph`) for explicit, debuggable control flow. The router uses keyword matching — no LLM cost per question, instant routing.

### Knowledge Base

The system ingests content from three sources:

| Source | Document Type | What's included |
|--------|--------------|-----------------|
| Project text fields | `project` | Title, description, technical approach, challenges, achievements, skills used, accuracy scores |
| Uploaded files per project | `project_documentation` | PDF, DOCX, TXT, MD, Python scripts (`.py`), Jupyter notebooks (`.ipynb`) |
| Resume models | `resume` | Personal info, education, experience, skills, certifications, languages |

### Auto-Ingestion (Zero Manual Work)

Every save in Django Admin automatically triggers re-ingestion in a background thread:

| Admin action | Signal | What happens |
|---|---|---|
| Save any Project | `post_save` on `Projects` | Re-embeds all text fields + all attached RAG files |
| Upload a `ProjectRAGFile` | `post_save` on `ProjectRAGFile` | Immediately processes and embeds the new file |
| Save any Resume model | `post_save` on `ResumeSetting`, `Education`, `Experience`, `Skill`, etc. | Full resume re-embedded |

No Celery or Redis required — uses Python's `threading.Thread(daemon=True)`. Errors are logged, never crash the admin save.

### Embeddings

- Model: `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional vectors)
- Storage: PostgreSQL (`DocumentChunk.embedding` as binary pickle)
- Retrieval: cosine similarity via `sklearn`, top-5 chunks per query
- No FAISS files, no stale cache — DB is the single source of truth

### LLM Support

The system tries LLMs in order, falling back gracefully:

1. **Gemini** (`gemini-2.5-flash`) — primary, free tier
2. **Anthropic Claude** (`claude-haiku-4-5`) — fallback
3. **OpenAI** (`gpt-4o-mini`) — fallback
4. **Built-in fallback message** — always shows something, never silent failure

Both streaming (Server-Sent Events) and non-streaming modes are supported.

### Routes

| Route | Triggered by | Searches |
|-------|-------------|---------|
| `cv` | "resume", "cv", "skills", "experience", "education" | `resume`, `skill` |
| `thesis` | "thesis", "dissertation", "research", "paper" | `project_documentation`, `project` |
| `ml_model` | "model", "accuracy", "prediction", "train" | `project`, `project_documentation` |
| `projects` | "project", "built", "kaggle", "github" | `project`, `project_documentation` |
| `general` | everything else | all document types |

### File Structure

```
rag_system/
├── graph/
│   ├── state.py          # AgentState TypedDict
│   ├── nodes.py          # router, search, generate, verify nodes
│   └── graph.py          # LangGraph StateGraph compiled to rag_graph
├── services/
│   ├── document_processor.py   # reads PDF/DOCX/TXT/MD/PY/IPYNB, chunks text
│   ├── embedding_service.py    # sentence-transformers, DB storage/retrieval
│   ├── retrieval_service.py    # cosine similarity search
│   ├── generation_service.py   # Gemini/Anthropic/OpenAI with streaming
│   └── rag_service.py          # orchestrates query() and stream_query()
├── management/commands/
│   └── ingest_from_db.py       # one-time bulk ingestion command
├── models.py             # Document, DocumentChunk, ChatSession, QueryLog
├── signals.py            # auto-ingestion on every admin save
├── views.py              # stream_api (SSE), query_api, sessions_api
└── apps.py               # connects signals in ready()
```

### API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| `POST` | `/rag/stream/` | Streaming chat (Server-Sent Events) |
| `POST` | `/rag/query/` | Non-streaming query (JSON response) |
| `GET/POST` | `/rag/sessions/` | List or create chat sessions |
| `GET/PATCH/DELETE` | `/rag/sessions/<id>/` | Session detail, rename, delete |
| `GET` | `/rag/chat/` | Chat UI page |

**Streaming request body:**
```json
{
  "question": "What projects has Hasan worked on?",
  "document_type": "all",
  "session_id": "optional-uuid"
}
```

**LangGraph request body (non-streaming, smart routing + self-correction):**
```json
{
  "question": "Tell me about the seizure detection model",
  "use_langgraph": true,
  "session_id": "optional-uuid"
}
```

### Setup

**Environment variables required:**
```env
GEMINI_API_KEY=your-key        # primary LLM (free tier available)
ANTHROPIC_API_KEY=             # optional fallback
OPENAI_API_KEY=                # optional fallback
```

**Initial ingestion** (run once — after that, signals handle everything):
```bash
python manage.py ingest_from_db
```

**Per-project ingestion:**
```bash
python manage.py ingest_from_db --project "Seizure Detection"
```

**Resume only:**
```bash
python manage.py ingest_from_db --type resume
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.2, Python 3.11 |
| Database | PostgreSQL (Neon serverless) |
| AI / RAG | LangGraph, sentence-transformers, Gemini 2.5 Flash |
| ML Models | scikit-learn, PyTorch, CatBoost, LightGBM |
| Frontend | Vanilla JS, Bootstrap 5 |
| Storage | Azure App Service Storage (`/home/media`) |
| Deployment | Azure App Service, Docker, GitHub Actions CI/CD |

---

## Projects with Live Demo

Projects can have a live prediction demo powered by the inference system. Each project can define a handler (tabular input or file upload) and an optional Azure ML managed endpoint for cloud-based inference with local model fallback.

---

## License

MIT
