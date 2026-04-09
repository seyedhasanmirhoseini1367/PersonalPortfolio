# ── Stage 1: Build dependencies ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for Python packages (numpy, Pillow, lxml, pycairo, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libpq-dev \
        libffi-dev \
        libssl-dev \
        libjpeg-dev \
        zlib1g-dev \
        libxml2-dev \
        libxslt1-dev \
        libcairo2-dev \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install torch CPU-only first (avoids downloading multi-GB CUDA wheels)
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir \
        torch==$(grep -i "^torch==" requirements.txt | cut -d= -f3) \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu


# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libjpeg62-turbo \
        zlib1g \
        libxml2 \
        libxslt1.1 \
        libcairo2 \
        libopenblas0 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy project source
COPY . .

# Create non-root user
RUN addgroup --system app && adduser --system --ingroup app app \
 && chown -R app:app /app

USER app

# Collect static files at build time
# SECRET_KEY is required by Django settings even for collectstatic — use a dummy value
ENV SECRET_KEY=build-time-dummy-not-used-in-production \
    DEBUG=False \
    ALLOWED_HOSTS=localhost \
    DATABASE_URL=""
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["bash", "startup.sh"]
