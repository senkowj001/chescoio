"""
Brand-scoped sitemaps (Sprint 5).

Each sitemap is instantiated with the current request.brand (see
core.views.sitemap), so a multi-brand backend emits a correct, brand-specific
sitemap for whichever host is being served — chesco.io lists chesco.io's
products and pages, and a second brand front would list its own with no code
change. Everything is served over https (protocol='https').
"""

from django.contrib import sitemaps
from django.urls import reverse

from catalog.models import Product

from .models import StaticPage


class _BrandSitemap(sitemaps.Sitemap):
    """Base: carries the active brand and forces https URLs."""

    protocol = 'https'

    def __init__(self, brand):
        self.brand = brand


class StaticViewSitemap(_BrandSitemap):
    """The evergreen view pages (home + shop index)."""

    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return ['core:home', 'catalog:product_list']

    def location(self, item):
        return reverse(item)


class ProductSitemap(_BrandSitemap):
    """Every published product for this brand."""

    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return list(
            Product.objects.filter(brand=self.brand, is_published=True)
        )

    def lastmod(self, obj):
        return obj.updated_at

    # location() falls back to obj.get_absolute_url() on the base Sitemap.


class StaticPageSitemap(_BrandSitemap):
    """Every published static page for this brand (about, size-guide, and any
    legal pages once John publishes them)."""

    changefreq = 'monthly'
    priority = 0.4

    def items(self):
        return list(
            StaticPage.objects.filter(brand=self.brand, is_published=True)
        )

    def lastmod(self, obj):
        return obj.updated_at

    # location() falls back to obj.get_absolute_url() on the base Sitemap.
