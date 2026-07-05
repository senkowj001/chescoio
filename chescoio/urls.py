"""
URL configuration for chescoio project.

Per-app URL modules are included here; BrandMiddleware has already attached
request.brand by the time any view runs.
"""

from django.contrib import admin
from django.urls import include, path

# Branded error handlers (Sprint 5). Django imports these by dotted path.
# page_not_found handles a 404 within a valid brand (the unknown-hostname 404
# is served by BrandMiddleware -> brands/not_found.html); server_error renders
# a self-contained 500 that doesn't depend on context processors.
handler404 = 'core.views.page_not_found'
handler500 = 'core.views.server_error'

urlpatterns = [
    # Admin is mounted at /ct-ops/ (not the well-known /admin/) to cut down on
    # automated bot probing of the default path. Admin's own URLs reverse
    # relative to this prefix via the `admin:` namespace, so nothing inside
    # admin needs to change. Do NOT reference this path in robots.txt, the
    # sitemap, or any public template — obscurity only helps if it stays quiet.
    path('ct-ops/', admin.site.urls),

    # Catalog (Sprint 2): /shop/ and /shop/<slug>/
    path('', include('catalog.urls', namespace='catalog')),

    # Orders (Sprint 2 stub for Printify webhook; Sprint 3 for cart/checkout)
    path('', include('orders.urls', namespace='orders')),

    # Brand-aware homepage and shared marketing routes
    path('', include('core.urls', namespace='core')),
]
