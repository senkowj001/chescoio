"""
Brand resolution middleware.

Attaches `request.brand` based on the inbound Host header. The bare apex is
matched (www. is stripped) against Brand.domain.

In DEBUG mode, unknown hosts fall back to the first active Brand, so local
dev at localhost / 127.0.0.1 works without a hosts-file workaround.

In production, unknown hosts get a branded 404 page, except for /admin URLs
(which must remain reachable via chescoio.herokuapp.com before DNS is set up).
"""

from django.conf import settings
from django.shortcuts import render

from .models import Brand


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
