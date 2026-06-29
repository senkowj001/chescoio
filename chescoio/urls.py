"""
URL configuration for chescoio project.

Per-app URL modules are included here; BrandMiddleware has already attached
request.brand by the time any view runs.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),

    # Catalog (Sprint 2): /shop/ and /shop/<slug>/
    path('', include('catalog.urls', namespace='catalog')),

    # Orders (Sprint 2 stub for Printify webhook; Sprint 3 for cart/checkout)
    path('', include('orders.urls', namespace='orders')),

    # Brand-aware homepage and shared marketing routes
    path('', include('core.urls', namespace='core')),
]
