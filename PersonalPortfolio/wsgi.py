"""
WSGI config for HasanAI project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PersonalPortfolio.settings')

application = get_wsgi_application()

# Content generation queue worker (one thread in the web process; see
# content_generator/worker.py). Started here so management commands and
# tests never run it.
from content_generator import worker as _generation_worker  # noqa: E402

_generation_worker.start()
