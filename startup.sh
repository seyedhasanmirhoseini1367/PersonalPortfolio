#!/bin/bash
# Azure App Service startup script
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Create superuser if it doesn't exist yet
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='seyed').exists():
    User.objects.create_superuser('seyed', 'seyed@example.com', 'Seyed@2024')
    print('Superuser created.')
else:
    print('Superuser already exists.')
"
gunicorn PersonalPortfolio.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
