"""
Brand resolution middleware.

Attaches `request.brand` based on the inbound Host header. The bare apex is
matched (www. is stripped) against Brand.domain.

In DEBUG mode, unknown hosts fall back to the first active Brand, so local
dev at localhost / 127.0.0.1 works without a hosts-file workaround.

In production, unknown hosts get a branded 404 page, except for /admin URLs
(which must remain reachable via chescoio.herokuapp.com before DNS is set up).

This module also hosts ForceWwwRedirectMiddleware, which canonicalizes
apex-domain traffic (e.g. chesco.io) to the www subdomain in a single 301.
"""

from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import render

from .models import Brand


class ForceWwwRedirectMiddleware:
    """
    Redirect apex-domain traffic to the www subdomain.

    Reads settings.FORCE_WWW_DOMAINS (an iterable of bare apex domain strings).
    A request whose Host header matches one of those domains is 301-redirected
    to `https://www.<host><path>?<query>`. Anything else passes through.

    Why this exists:
      - SEO: pick one canonical host so search engines don't split link equity
        between chesco.io and www.chesco.io.
      - Cookies: apex and subdomain get separate cookie jars by default;
        forcing traffic to www keeps sessions on one host.
      - Consistency: whichever the customer types, they see the same URL.

    Why it runs first in the middleware chain (before SecurityMiddleware):
      - Consolidates http-apex to https-www into a single 301 hop.
      - Avoids a wasted BrandMiddleware DB query on requests we're about to
        redirect away anyway.
      - Cheapest possible response for the redirect path; no session, no CSRF
        cookie work, no template rendering.

    Dev is a no-op: local.py doesn't set FORCE_WWW_DOMAINS, so the initializer
    resolves an empty frozenset and __call__ short-circuits on the emptiness
    check without even touching the request.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.force_www_domains = frozenset(
            getattr(settings, 'FORCE_WWW_DOMAINS', ()) or ()
        )

    def __call__(self, request):
        if self.force_www_domains:
            host = request.get_host().split(':')[0].lower()
            if host in self.force_www_domains:
                target = f'https://www.{host}{request.get_full_path()}'
                return HttpResponsePermanentRedirect(target)
        return self.get_response(request)


class BrandMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        if host.startswith('www.'):
            host = host[4:]

        try:
            request.brand = Brand.objects.get(domain=host, is_active=True)
        except Brand.DoesNotExist:
            request.brand = None

            # Dev convenience: any unknown host resolves to the first active brand
            # so you don't need /etc/hosts entries to develop locally.
            if settings.DEBUG:
                request.brand = Brand.objects.filter(is_active=True).first()

            # Production: unknown host = branded 404, unless they're heading to admin.
            # Admin must remain reachable on chescoio.herokuapp.com before DNS is live.
            if request.brand is None and not request.path.startswith('/admin'):
                return render(request, 'brands/not_found.html', status=404)

        return self.get_response(request)
