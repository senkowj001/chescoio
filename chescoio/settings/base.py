"""
Django base settings for chescoio.

Common settings shared across environments. Environment-specific overrides
live in local.py and production.py.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# settings/base.py is 3 levels deep: BASE_DIR -> chescoio -> settings -> base.py
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# =============================================================================
# Core Django
# =============================================================================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'django.contrib.humanize',

    # Third-party
    'mailer',  # django-mailer: queues outbound email to the DB; flushed by send_mail mgmt command

    # Local apps
    'brands',
    'catalog',  # placeholder for Sprint 2 (Printify products)
    'orders',   # placeholder for Sprint 3 (cart) / Sprint 4 (orders)
    'core',
]

MIDDLEWARE = [
    'brands.middleware.ForceWwwRedirectMiddleware',  # Apex → www canonicalization (no-op in dev)
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Serve static files efficiently
    'brands.middleware.BrandMiddleware',           # Resolve request.brand from hostname
    'django.middleware.gzip.GZipMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'chescoio.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'orders.context_processors.cart',
            ],
        },
    },
]

WSGI_APPLICATION = 'chescoio.wsgi.application'


# =============================================================================
# Password validation
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# =============================================================================
# Internationalization
# =============================================================================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'  # Chester County, PA
USE_I18N = True
USE_TZ = True


# =============================================================================
# Static files
# =============================================================================

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise compression and caching
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# =============================================================================
# Media
# =============================================================================

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# =============================================================================
# Email (django-mailer queues to DB; real transport configured per-env)
# =============================================================================

EMAIL_BACKEND = 'mailer.backend.DbBackend'
# MAILER_EMAIL_BACKEND is set per-environment (console in local, SMTP in production)


# =============================================================================
# Printify (Sprint 2+)
# =============================================================================

# Personal Access Token from Printify dashboard (My Account > Connections).
# Required by catalog.printify_client.PrintifyClient and the sync_printify_products
# management command. Per-brand printify_shop_id lives on the Brand model.
PRINTIFY_ACCESS_TOKEN = os.environ.get('PRINTIFY_ACCESS_TOKEN', '')

# Shared secret used to verify HMAC signatures on inbound Printify webhooks.
# Set when registering the webhook in Printify > Settings > Webhooks. Full
# signature verification lands in Sprint 4; the Sprint 2 endpoint stub only
# logs payloads to WebhookEvent.
PRINTIFY_WEBHOOK_SECRET = os.environ.get('PRINTIFY_WEBHOOK_SECRET', '')


# =============================================================================
# Stripe (Sprint 3+)
# =============================================================================

# Stripe API keys. Use sk_test_... / pk_test_... during development; flip to
# sk_live_... / pk_live_... at Sprint 5 launch. Stripe Tax is enabled via the
# `automatic_tax` flag on Checkout Sessions — no code config needed here, but
# PA must be registered under Stripe Tax > Registrations in the dashboard for
# the PA clothing exemption ($0 sales tax) to apply.
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')

# Webhook signing secret. For dev: get from `stripe listen --forward-to ...`.
# For prod: from Stripe dashboard > Developers > Webhooks > endpoint details.
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

# Cart cleanup threshold. The clear_old_carts management command deletes carts
# whose updated_at is older than this. 7 days per the canonical models inventory
# (sprintplans/eg_apparel_sprint_plan.md). Note: Django's default
# SESSION_COOKIE_AGE is 14 days, so a returning visitor between day 7 and 14
# will have an intact session with an empty cart — that's intentional.
CART_EXPIRY_DAYS = int(os.environ.get('CART_EXPIRY_DAYS', 7))

# Shipping rate quote cache TTL in the session (seconds). After this elapses
# the cart re-quotes shipping from Printify on the next checkout attempt. Short
# enough that stale rates don't follow customers around, long enough that
# tabbing away and back doesn't trigger redundant API calls.
CART_SHIPPING_QUOTE_TTL_SECONDS = int(os.environ.get('CART_SHIPPING_QUOTE_TTL_SECONDS', 900))



# =============================================================================
# Misc
# =============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'admin:login'


# =============================================================================
# Logging
# =============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
    },
}
