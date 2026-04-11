#!/bin/bash
# Azure App Service startup script

set -e  # Stop script if any command fails

echo "Starting deployment..."

# Run database migrations
echo "Creating persistent media directories..."
mkdir -p /home/media/profile_pics /home/media/stories /home/media/projects/models

echo "Running migrations..."
python manage.py migrate --noinput

# Create superuser if not exists
echo "Ensuring superuser exists..."
python manage.py ensure_superuser

echo "Starting gunicorn server..."
# Start the server
gunicorn PersonalPortfolio.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -