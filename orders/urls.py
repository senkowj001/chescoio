"""
Orders URL routes.

Sprint 2: just the Printify webhook receiver stub.
Sprint 3 adds cart and Stripe checkout routes; Sprint 4 adds the Stripe
webhook and order lookup.
"""

from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    # Printify webhook (Sprint 2 stub; full handling in Sprint 4)
    path('webhooks/printify/', views.printify_webhook, name='printify_webhook'),
]
