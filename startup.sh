#!/bin/bash
# Startup script — works on Railway and Azure App Service

echo "Starting deployment..."

# On Azure, WEBSITE_SITE_NAME is set — create persistent media dirs there.
# On Railway/local, media lives inside the project directory (BASE_DIR/media).
if [ -n "$WEBSITE_SITE_NAME" ]; then
    echo "Azure detected — creating /home/media directories..."
    mkdir -p /home/media/profile_pics /home/media/stories /home/media/projects/models
else
    echo "Railway/local detected — creating local media directories..."
    mkdir -p media/profile_pics media/stories media/projects/models
fi

echo "Running migrations..."
python manage.py migrate --noinput

echo "Ensuring superuser exists..."
python manage.py ensure_superuser

echo "Populating resume data (skips if already present)..."
python manage.py populate_resume --if-empty || echo "populate_resume skipped or errored (non-fatal)"

echo "Starting gunicorn..."
gunicorn PersonalPortfolio.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 1 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
