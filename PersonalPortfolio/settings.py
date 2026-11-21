"""
Django settings for PersonalPortfolio.
All secrets and environment-specific values come from .env (never hardcoded).
"""
import os
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ───────────────────────────────────────────────────────────────────
SECRET_KEY = config('SECRET_KEY', default='build-time-dummy-not-for-production')
DEBUG       = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())
OWNER_IPS     = config('OWNER_IPS', default='127.0.0.1', cast=Csv())

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
    'django.contrib.sites',
    'crispy_forms',
    'crispy_bootstrap5',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.github',

    # Project apps
    'projects',
    'contact',
    'resume',
    'rag_system',
    'stories',
    'accounts',
    'monitoring',
    'content_generator',
    'kaggle_archive',
    'model_internals',
    'sports',

    'storages',
]

AUTH_USER_MODEL = 'accounts.CustomUser'

SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
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
# ── django-allauth ────────────────────────────────────────────────────────────
ACCOUNT_EMAIL_REQUIRED          = True
ACCOUNT_USERNAME_REQUIRED       = False
ACCOUNT_AUTHENTICATION_METHOD   = 'email'
ACCOUNT_EMAIL_VERIFICATION      = 'none'
ACCOUNT_SESSION_REMEMBER        = True   # persist login across browser close / redeploy
SOCIALACCOUNT_AUTO_SIGNUP       = True
SOCIALACCOUNT_LOGIN_ON_GET      = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION             = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/'

SESSION_COOKIE_AGE     = 60 * 60 * 24 * 30   # 30 days
SESSION_SAVE_EVERY_REQUEST = True              # refresh expiry on each request

# Logs the real reason when a Google/GitHub login fails (see accounts/adapters.py).
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.LoggingSocialAccountAdapter'

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID',     default=''),
            'secret':    config('GOOGLE_CLIENT_SECRET', default=''),
        },
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'OAUTH_PKCE_ENABLED': True,
    },
    'github': {
        'APP': {
            'client_id': config('GITHUB_CLIENT_ID',     default=''),
            'secret':    config('GITHUB_CLIENT_SECRET', default=''),
        },
        'SCOPE': ['user:email', 'read:user'],
    },
}

# ── Form field limits ─────────────────────────────────────────────────────────
# Django's default is 1000, a guard against a POST with a huge number of fields
# exhausting CPU in the parser.
#
# This was raised because the "How Models Work" admin page posted one editable
# inline form per content block -- 1,133 controls on the 136-block Transformer
# walkthrough -- so saving it failed with TooManyFieldsSent even when the only
# edit was a cover image. That inline is now read-only (the blocks are rebuilt
# from the notebooks on every deploy, so editing them was futile anyway), which
# brought the same form down to 312 controls.
#
# So the original trigger is gone and the default would now suffice. Kept as
# headroom: the section keeps growing, and a walkthrough three times longer than
# the current worst case should not fail to save.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ── Media files ───────────────────────────────────────────────────────────────
MEDIA_URL = '/media/'

# We check if the environment variable 'WEBSITE_SITE_NAME' exists.
# Azure always sets this variable, while Railway and your PC do not.
if os.environ.get('WEBSITE_SITE_NAME'):
    # If we are on Azure, use the persistent home directory
    MEDIA_ROOT = Path('/home/media')
else:
    # If we are on Railway or Local PC, use the project folder
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
GROQ_API_KEY            = config('GROQ_API_KEY',            default='')
MONITORING_ALERT_EMAIL  = config('MONITORING_ALERT_EMAIL',  default='')
SLACK_WEBHOOK_URL       = config('SLACK_WEBHOOK_URL',       default='')

# ── Synthetic Monitor ─────────────────────────────────────────────────────
SYNTHETIC_MONITOR = {
    'DATA_DIR':        config('SYNTHETIC_DATA_DIR', default=''),
    'TARGET_CSV':      config('SYNTHETIC_TARGET_CSV', default=''),
    'PROJECT_TITLE':   'Seizure Detection',
    'MIN_SAMPLES':     100,
    'MAX_SAMPLES':     200,
    'INTERVAL_MINUTES': config('MONITOR_INTERVAL_MINUTES', default=30, cast=int),
}

# ── RAG Configuration ─────────────────────────────────────────────────────────
RAG_CONFIG = {
    'EMBEDDING_MODEL':  'models/text-embedding-004',
    'VECTOR_STORE_PATH': BASE_DIR / 'rag_system' / 'vector_store',
    'DOCUMENTS_PATH':    BASE_DIR / 'rag_system' / 'documents',
    'CHUNK_SIZE':        300,
    'CHUNK_OVERLAP':     50,
    'GEMINI_MODEL':      'gemini-2.0-flash',
    'ANTHROPIC_MODEL':   'claude-haiku-4-5-20251001',
    'OPENAI_MODEL':      'gpt-4o-mini',
    'GROQ_MODEL':        'llama-3.1-8b-instant',
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
    SECURE_PROXY_SSL_HEADER        = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT            = False
    SECURE_HSTS_SECONDS            = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE          = True
    CSRF_COOKIE_SECURE             = True
    SECURE_BROWSER_XSS_FILTER      = True
    SECURE_CONTENT_TYPE_NOSNIFF    = True
    # Required for Cloudflare + Railway: list trusted origins for CSRF
    _csrf_origins = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())
    if _csrf_origins:
        CSRF_TRUSTED_ORIGINS = list(_csrf_origins)

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

# ── Azure Blob Storage (Media files) ──────────────────────────────────────────
# Disabled: media files are served from /home/media (Azure App Service Storage,
# persistent across deployments) in production, and local media/ in development.
# AZURE_ACCOUNT_NAME / AZURE_ACCOUNT_KEY are kept for potential future use.
AZURE_ACCOUNT_NAME = config('AZURE_ACCOUNT_NAME', default='') or os.environ.get('AZURE_ACCOUNT_NAME', '')
AZURE_ACCOUNT_KEY = config('AZURE_ACCOUNT_KEY', default='') or os.environ.get('AZURE_ACCOUNT_KEY', '')
AZURE_CONTAINER = config('AZURE_CONTAINER', default='media') or os.environ.get('AZURE_CONTAINER', 'media')