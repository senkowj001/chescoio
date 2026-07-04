"""
Core URL routes.

Sprint 5 adds the marketing / legal / SEO surface on top of the Sprint 1
homepage. Canonical legal/marketing pages get clean top-level URLs (each
wired to the same static_page view via a fixed slug); ad-hoc pages fall back
to /p/<slug>/. robots.txt and sitemap.xml are dynamic and brand-scoped.

These routes are included last in chescoio/urls.py (after catalog's shop/ and
orders' cart//checkout//webhooks//orders/ prefixes), so none of the top-level
slugs here collide with those apps.
"""

from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),

    # Canonical static pages (fixed slugs -> friendly URLs).
    path('about/', views.static_page, {'slug': 'about'}, name='about'),
    path('privacy/', views.static_page, {'slug': 'privacy'}, name='privacy'),
    path('terms/', views.static_page, {'slug': 'terms'}, name='terms'),
    path('returns/', views.static_page, {'slug': 'returns'}, name='returns'),
    path('shipping/', views.static_page, {'slug': 'shipping'}, name='shipping'),
    path('size-guide/', views.static_page, {'slug': 'size-guide'}, name='size_guide'),

    # Ad-hoc / future one-off pages.
    path('p/<slug:slug>/', views.static_page, name='static_page'),

    # Contact + email signup.
    path('contact/', views.contact, name='contact'),
    path('signup/', views.email_signup, name='email_signup'),

    # SEO.
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('sitemap.xml', views.sitemap, name='sitemap'),
]
