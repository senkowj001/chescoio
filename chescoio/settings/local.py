"""
Local development settings.

Usage: DJANGO_SETTINGS_MODULE=chescoio.settings.local
"""

import os
import dj_database_url
from dotenv import load_dotenv

from .base import *  # noqa: F401, F403

# Load .env from project root for local dev
load_dotenv(BASE_DIR / '.env')


# =============================================================================
# Debug
# =============================================================================

DEBUG = True

SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-local-dev-only-change-in-production',
)


# =============================================================================
# Hosts
# =============================================================================

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '[::1]',
    'chesco.localhost',      # For local multi-brand testing: add to hosts file
    'www.chesco.localhost',  # 127.0.0.1 chesco.localhost www.chesco.localhost
]


# =============================================================================
# Database
# =============================================================================

# Local default: SQLite at <project-root>/db.sqlite3. Override with DATABASE_URL
# in .env (e.g. postgres://chescoio:password@localhost:5432/chescoio) to run
# against local Postgres.
#
# We deliberately don't use dj_database_url.config(default=...) here: on Windows
# the interpolated sqlite URL contains backslashes that some versions of
# dj_database_url fail to parse, silently falling back to the dummy DB backend.
# Explicit config sidesteps that entirely.
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=0),
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# =============================================================================
# Email — console backend for dev
# =============================================================================

# django-mailer still queues to DB (EMAIL_BACKEND in base.py); but when the
# queue is flushed via `python manage.py send_mail`, it prints to the console
# instead of sending real email.
MAILER_EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


# =============================================================================
# Static files — use simple storage in dev (faster, no manifest required)
# =============================================================================

STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'


# =============================================================================
# Security (relaxed for local HTTP)
# =============================================================================

CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
X_FRAME_OPTIONS = 'SAMEORIGIN'
