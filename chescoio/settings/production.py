"""
Heroku production settings for chescoio.

Usage (Heroku config var):
  DJANGO_SETTINGS_MODULE=chescoio.settings.production
"""

import os
import dj_database_url

from .base import *  # noqa: F401, F403


# =============================================================================
# Debug — always off in production
# =============================================================================

DEBUG = False

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError('SECRET_KEY environment variable is required in production')

if len(SECRET_KEY) < 50:
    raise ValueError('SECRET_KEY must be at least 50 characters in production')


# =============================================================================
# Allowed hosts
# =============================================================================

# Custom brand domains are validated by BrandMiddleware against the Brand model,
# but Django's host header validation runs BEFORE middleware, so we must list
# every domain Heroku may receive traffic for. Add additional brand domains
# here when adding a new Brand record.
ALLOWED_HOSTS = [
    'chesco.io',
    'www.chesco.io',
    'chescoio.herokuapp.com',
]

HEROKU_APP_NAME = os.environ.get('HEROKU_APP_NAME')
if HEROKU_APP_NAME:
    candidate = f'{HEROKU_APP_NAME}.herokuapp.com'
    if candidate not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(candidate)


# =============================================================================
# Database — Heroku Postgres
# =============================================================================

# conn_max_age=60 (down from the Django default of 600) trades a small
# per-request reconnect cost for eliminating the class of stale-connection
# 500s we hit on 2026-07-03. On a low-traffic pre-launch site, a persistent
# connection can sit idle long enough for Heroku Postgres's proxy to reap
# it silently; the next request then times out on a dead socket. At 60s
# TTL, idle intervals rarely span the full lifetime, and Django's
# CONN_HEALTH_CHECKS below detects dead connections before use anyway.
# Revisit if traffic ever justifies chasing the reconnect overhead.
DATABASES = {
    'default': dj_database_url.config(
        conn_max_age=60,
        ssl_require=True,
    )
}

DATABASES['default']['CONN_HEALTH_CHECKS'] = True

# psycopg2 connection-level timeouts (mirrors HuntScrape).
DATABASES['default'].setdefault('OPTIONS', {})
DATABASES['default']['OPTIONS'].update({
    'connect_timeout': 15,
    'keepalives': 1,
    'keepalives_idle': 30,
    'keepalives_interval': 10,
    'keepalives_count': 3,
    'options': '-c statement_timeout=25000',
})


# =============================================================================
# Security
# =============================================================================

# Heroku's router terminates SSL and sets X-Forwarded-Proto.
# Without Cloudflare in front of us, this is the only proxy in the chain.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True

# Cookies
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# HSTS (1 year, include subdomains, preload)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Misc hardening
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_BROWSER_XSS_FILTER = True


# =============================================================================
# CSRF trusted origins
# =============================================================================

CSRF_TRUSTED_ORIGINS = [
    'https://chesco.io',
    'https://www.chesco.io',
    'https://chescoio.herokuapp.com',
]


# =============================================================================
# Canonical host: force apex → www
# =============================================================================

# ForceWwwRedirectMiddleware 301-redirects requests hitting these apex
# domains to their www subdomain. Add a domain here when you add a new
# Brand and want www to be the canonical host for it.
FORCE_WWW_DOMAINS = ['chesco.io']


# =============================================================================
# Email — Hostinger SMTP via django-mailer queue
# =============================================================================

# EMAIL_BACKEND = 'mailer.backend.DbBackend' is set in base.py (queue to DB).
# When the queue is flushed by `python manage.py send_mail`, mail goes via SMTP:
MAILER_EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.hostinger.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'hello@chesco.io')
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)


# =============================================================================
# Admins — receive error notifications
# =============================================================================

ADMINS = []
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
if ADMIN_EMAIL:
    ADMINS.append(('Admin', ADMIN_EMAIL))


# =============================================================================
# Logging — production level
# =============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console', 'mail_admins'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}


# =============================================================================
# File upload limits
# =============================================================================

DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10 MB
