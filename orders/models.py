"""
Orders app models.

Sprint 2 lands the WebhookEvent model used as a shared idempotency / audit
log for inbound Stripe and Printify webhooks. Full Order, OrderItem,
Cart, CartItem, and EmailSignup models arrive in Sprints 3-5 per the plan.
"""

from django.db import models


class WebhookEvent(models.Model):
    """
    Idempotency + audit log for every Stripe and Printify webhook received.

    Stripe and Printify both deliver events with a unique `id` (and may
    redeliver them). We dedupe on (source, event_id) so a second receipt is
    a no-op. The payload is retained for forensic debugging.

    Sprint 4 will add per-source signature verification and concrete handlers
    that flip `processed_at` once the event has been applied.
    """

    SOURCE_STRIPE = 'stripe'
    SOURCE_PRINTIFY = 'printify'
    SOURCE_CHOICES = [
        (SOURCE_STRIPE, 'Stripe'),
        (SOURCE_PRINTIFY, 'Printify'),
    ]

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, db_index=True)
    event_id = models.CharField(max_length=255, db_index=True)
    event_type = models.CharField(max_length=100, db_index=True, blank=True)
    payload = models.JSONField()

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-received_at']
        unique_together = [('source', 'event_id')]

    def __str__(self):
        return f'{self.source}:{self.event_type} ({self.event_id})'
