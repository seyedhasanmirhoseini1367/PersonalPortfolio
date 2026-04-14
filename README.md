# Hasan Mirhoseini — AI Portfolio

A personal portfolio website for a Data Scientist and ML Engineer based in Finland. Built with Django, it goes beyond a static CV: visitors can interact with a live AI assistant, run real ML model predictions, and read technical blog posts — all in one place.

**Live site:** [hasanai-bwgfgtffcka4arah.westeurope-01.azurewebsites.net](https://hasanai-bwgfgtffcka4arah.westeurope-01.azurewebsites.net/)

---

## What the Website Does

| Section | Description |
|---------|-------------|
| **Home** | Hero introduction, stats, featured ML models, skills overview, GitHub activity |
| **ML Models** | Full portfolio of data science projects with live prediction demos |
| **Resume** | Interactive resume with education, experience, skills, certifications |
| **Stories** | Technical blog posts written in a rich-text editor |
| **AI Assistant** | RAG-powered chat that answers questions about the portfolio |
| **Admin** | Django admin for managing all content |

The site is deployed on **Azure App Service** with a **PostgreSQL** database (Neon), **GitHub Actions** CI/CD, and persistent media storage via Azure App Service Storage (`/home/media`).

---

## ML Models

The ML Models section showcases data science and machine learning work across multiple domains. Each model entry includes:

- **Project type**: Kaggle Competition, Personal ML Project, Deep Learning, NLP, Time Series, Data Analysis, Academic, Work
- **Technical details**: description, problem statement, technical approach, challenges, key achievements, lessons learned
- **Performance metrics**: accuracy score, Kaggle rank and percentile
- **Skills & libraries used**: full breakdown of tools applied
- **Live prediction demo**: some models have an interactive demo (see below)

### Live Prediction Demos

Projects with `prediction_endpoint = True` expose a live demo directly on the project page. Two input modes are supported:

**Tabular input** — the user fills in a form with feature values, the model returns a prediction with a confidence score and an AI-generated plain-language interpretation.

**File upload** — the user uploads a data file (CSV, Parquet, etc.), a registered handler processes it through the model pipeline, and the result is returned. Example: the EEG Seizure Detection model accepts a Parquet file of EEG signal segments and returns a seizure/no-seizure classification.

The inference system uses a handler registry (`@register("handler_name")`) so new model types can be added without changing the core inference code. Azure ML managed endpoints are supported as a cloud fallback, with automatic drop-through to the local model when not configured.

### RAG Documents per Model

Each ML model can have multiple knowledge files attached (PDF, DOCX, TXT, Markdown, Python scripts, Jupyter notebooks). These are automatically ingested into the RAG knowledge base whenever saved, so the AI assistant can answer detailed questions about any model.

---

## RAG System — AI Assistant

The AI assistant answers natural language questions about the portfolio. It uses **Retrieval-Augmented Generation (RAG)**: it searches a knowledge base built from all portfolio content, retrieves the most relevant passages, and passes them to an LLM to generate a grounded answer.

### Architecture

```
User Question
     │
     ▼
┌─────────────┐
│ Router Node │  ← keyword-based, free (no LLM call per question)
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
              good ◄───┤───► needs_retry → back to search node (max 2 retries)
                       ▼
                      END
```

Built with **LangGraph** (`StateGraph`) for explicit, debuggable control flow.

### Routing

| Route | Triggered by keywords | Searches |
|-------|----------------------|---------|
| `cv` | resume, cv, skills, experience, education, background | `resume`, `skill` |
| `thesis` | thesis, dissertation, research, paper, study | `project_documentation`, `project` |
| `ml_model` | model, accuracy, prediction, train, dataset | `project`, `project_documentation` |
| `projects` | project, built, kaggle, github, implement | `project`, `project_documentation` |
| `general` | everything else | all document types |

### Knowledge Base

| Source | Document type | Content |
|--------|--------------|---------|
| ML Model text fields | `project` | Title, description, approach, challenges, achievements, skills, metrics |
| Uploaded files per model | `project_documentation` | PDF, DOCX, TXT, MD, `.py` scripts, `.ipynb` notebooks |
| Resume data | `resume` | Personal info, education, experience, skills, certifications, languages |

### Auto-Ingestion

Every admin save triggers re-ingestion automatically in a background thread — no manual commands needed:

| Admin action | What happens |
|---|---|
| Save any ML Model | Re-embeds all text fields + all attached RAG files |
| Upload a RAG file to a model | Immediately processed and embedded |
| Save any Resume section | Full resume re-embedded |

### Embeddings & Retrieval

- **Embedding model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional vectors)
- **Storage**: PostgreSQL — embeddings stored as binary in `DocumentChunk.embedding`
- **Retrieval**: cosine similarity (sklearn), top-5 chunks per query
- No FAISS files, no stale cache — the database is the single source of truth

### LLM Support

Tries LLMs in order, falls back gracefully:

1. **Gemini 2.5 Flash** (primary, free tier)
2. **Anthropic Claude Haiku** (fallback)
3. **OpenAI GPT-4o Mini** (fallback)
4. **Built-in fallback message** — never silent failure

Both streaming (Server-Sent Events) and non-streaming modes supported.

---

## Skills & Technologies Being Learned

### Machine Learning & Data Science
- **Supervised learning**: regression, classification, ensembles (XGBoost, LightGBM, CatBoost)
- **Deep learning**: neural networks, CNNs, RNNs, attention mechanisms (PyTorch, TensorFlow, Keras)
- **NLP**: text classification, embeddings, transformers (HuggingFace, sentence-transformers)
- **Time series**: feature engineering, forecasting, signal processing (MNE for EEG)
- **Model evaluation**: cross-validation, Kaggle competitions, performance metrics

### MLOps & Deployment
- **Experiment tracking**: MLflow (runs, metrics, artifact logging)
- **Model serving**: Django inference API, handler registry pattern
- **Cloud ML**: Azure ML managed online endpoints (REST API, graceful fallback)
- **Containerisation**: Docker, Azure App Service deployment
- **CI/CD**: GitHub Actions (build → test → push → deploy pipeline)

### AI & RAG
- **LangGraph**: StateGraph, conditional edges, self-correction loops
- **RAG pipeline**: chunking, embedding, cosine similarity retrieval, context injection
- **LLM APIs**: Gemini (google-genai), Anthropic, OpenAI — streaming and non-streaming
- **Document processing**: PDF (pypdf), DOCX (python-docx), Jupyter notebooks (JSON)

### Web Development
- **Backend**: Django 5, Django ORM, signals, management commands, admin customisation
- **Frontend**: HTML/CSS, JavaScript, Quill rich-text editor, Server-Sent Events (streaming)
- **Databases**: PostgreSQL (Neon serverless), Django migrations
- **APIs**: RESTful JSON APIs, SSE streaming endpoints

### Cloud & Infrastructure
- **Azure**: App Service, App Service Storage, Azure ML (in progress)
- **Storage**: persistent `/home/media` mount, local filesystem for dev
- **Environment management**: python-decouple, `.env` separation per environment

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.2, Python 3.11 |
| Database | PostgreSQL (Neon serverless) |
| AI / RAG | LangGraph, sentence-transformers, Gemini 2.5 Flash |
| ML Libraries | scikit-learn, PyTorch, CatBoost, LightGBM, MNE |
| Frontend | Vanilla JS, Bootstrap 5, Quill editor |
| Media storage | Azure App Service Storage (`/home/media`) |
| Deployment | Azure App Service, Docker, GitHub Actions CI/CD |

---

## Local Development

```bash
git clone https://github.com/seyedhasanmirhoseini1367/PersonalPortfolio.git
cd PersonalPortfolio
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# Copy and fill in your keys
cp .env.example .env

python manage.py migrate
python manage.py createsuperuser
python manage.py ingest_from_db   # build RAG knowledge base (run once)
python manage.py runserver
```

**Required `.env` keys:**
```env
SECRET_KEY=your-django-secret-key
DEBUG=True
GEMINI_API_KEY=your-gemini-key
DATABASE_URL=your-postgres-url
```

---

## License

MIT
