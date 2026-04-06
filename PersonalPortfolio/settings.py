"""
Django settings for PersonalPortfolio.
All secrets and environment-specific values come from .env (never hardcoded).
"""
import os
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ───────────────────────────────────────────────────────────────────
SECRET_KEY = config('SECRET_KEY')
DEBUG       = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# ── Application definition ─────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',

    # Third-party
    'crispy_forms',
    'crispy_bootstrap5',

    # Project apps
    'projects',
    'contact',
    'resume',
    'rag_system',
    'stories',
    'accounts',
    'monitoring',
]

AUTH_USER_MODEL = 'accounts.CustomUser'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',          # serve static files
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'PersonalPortfolio.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'PersonalPortfolio.wsgi.application'

# ── Database ───────────────────────────────────────────────────────────────────
# Uses SQLite locally; set DATABASE_URL in .env for PostgreSQL in production.
_db_url = config('DATABASE_URL', default='')
if _db_url:
    import dj_database_url
    DATABASES = {'default': dj_database_url.parse(_db_url, conn_max_age=600)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ── Password validation ────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internationalisation ───────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Europe/Helsinki'
USE_I18N      = True
USE_TZ        = True

# ── Static files ──────────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ── Media files ───────────────────────────────────────────────────────────────
MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── Default primary key ────────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Crispy Forms ───────────────────────────────────────────────────────────────
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK          = 'bootstrap5'

# ── Email ──────────────────────────────────────────────────────────────────────
_email_user = config('EMAIL_HOST_USER', default='')
if _email_user:
    EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST          = config('EMAIL_HOST',     default='smtp.gmail.com')
    EMAIL_PORT          = config('EMAIL_PORT',     default=587, cast=int)
    EMAIL_USE_TLS       = config('EMAIL_USE_TLS',  default=True, cast=bool)
    EMAIL_HOST_USER     = _email_user
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
else:
    # Dev: print emails to console instead of sending
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='seyedhasan.mirhoseini1367@gmail.com')

# ── AI / LLM API Keys ─────────────────────────────────────────────────────────
GEMINI_API_KEY          = config('GEMINI_API_KEY',          default='')
ANTHROPIC_API_KEY       = config('ANTHROPIC_API_KEY',       default='')
OPENAI_API_KEY          = config('OPENAI_API_KEY',          default='')
MONITORING_ALERT_EMAIL  = config('MONITORING_ALERT_EMAIL',  default='')

# ── RAG Configuration ─────────────────────────────────────────────────────────
RAG_CONFIG = {
    'EMBEDDING_MODEL':  'sentence-transformers/all-MiniLM-L6-v2',
    'VECTOR_STORE_PATH': BASE_DIR / 'rag_system' / 'vector_store',
    'DOCUMENTS_PATH':    BASE_DIR / 'rag_system' / 'documents',
    'CHUNK_SIZE':        1000,
    'CHUNK_OVERLAP':     200,
    'GEMINI_MODEL':      'models/gemini-2.5-flash',
    'ANTHROPIC_MODEL':   'claude-haiku-4-5-20251001',
    'OPENAI_MODEL':      'gpt-4o-mini',
    'MAX_TOKENS':        1200,
}

os.makedirs(RAG_CONFIG['VECTOR_STORE_PATH'], exist_ok=True)
os.makedirs(RAG_CONFIG['DOCUMENTS_PATH'],    exist_ok=True)

# ── ML / Data paths ───────────────────────────────────────────────────────────
# Local dataset paths — only used in development, never relied on in production
PERSONALITY_DATA_DIR = config(
    'PERSONALITY_DATA_DIR',
    default=str(BASE_DIR / 'datasets' / 'personality'),
)

# ── Production security (only active when DEBUG=False) ────────────────────────
if not DEBUG:
    SECURE_HSTS_SECONDS            = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_SSL_REDIRECT            = True
    SESSION_COOKIE_SECURE          = True
    CSRF_COOKIE_SECURE             = True
    SECURE_BROWSER_XSS_FILTER      = True
    SECURE_CONTENT_TYPE_NOSNIFF    = True

# ── Logging ───────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO' if DEBUG else 'WARNING', 'propagate': False},
    },
}
