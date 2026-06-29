"""
WSGI config for chescoio project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os

from django.core.wsgi import get_wsgi_application

# Heroku sets DJANGO_SETTINGS_MODULE=chescoio.settings.production as a config var.
# Local dev defaults to local settings.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chescoio.settings.local')

application = get_wsgi_application()
