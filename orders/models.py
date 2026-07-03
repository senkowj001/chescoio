"""
Orders app models.

Sprint 2 landed WebhookEvent (idempotency / audit log for inbound Stripe and
Printify webhooks).

Sprint 3 adds:
  - Cart, CartItem: session-keyed shopping cart for guest checkout
  - Order, OrderItem: a paid order record created from the Stripe webhook;
    line item prices are snapshotted at order time so future Variant price
    changes never rewrite history.

Sprint 4 will wire Order.status transitions to Printify webhook events and
populate printify_order_id / shipped_at / delivered_at.
"""

from django.db import models

from brands.models import Brand
from catalog.models import Variant


# =============================================================================
# Webhook audit log (Sprint 2)
# =============================================================================

class WebhookEvent(models.Model):
    """
    Idempotency + audit log for every Stripe and Printify webhook received.

    Stripe and Printify both deliver events with a unique `id` (and may
    redeliver them). We dedupe on (source, event_id) so a second receipt is
    a no-op. The payload is retained for forensic debugging.

    The webhook handler sets processed_at when a handler has successfully
    completed (used by retries / re-processing tooling).
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


# =============================================================================
# Cart (Sprint 3)
# =============================================================================

class Cart(models.Model):
    """
    Session-keyed shopping cart. Guest checkout only — no User FK.

    One Cart per (brand, session_key) pair. The `clear_old_carts` management
    command prunes carts older than settings.CART_EXPIRY_DAYS (7 by default).

    On a successful checkout, the Stripe webhook deletes the cart so it doesn't
    linger after the order is created.
    """

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name='carts')
    session_key = models.CharField(max_length=100, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = [('brand', 'session_key')]
        indexes = [
            models.Index(fields=['updated_at']),  # for cleanup queries
        ]

    def __str__(self):
        return f'Cart {self.pk} ({self.brand.domain}, session={self.session_key[:8]}\u2026)'

    @property
    def item_count(self) -> int:
        """Total quantity across all line items (not distinct variants)."""
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal_cents(self) -> int:
        return sum(item.line_total_cents for item in self.items.all())


class CartItem(models.Model):
    """
    A single variant-quantity line in a Cart.

    Adding the same Variant twice updates the existing row (sum quantities)
    rather than creating duplicate lines — enforced at the view layer via
    update_or_create on (cart, variant).
    """

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        unique_together = [('cart', 'variant')]

    def __str__(self):
        return f'{self.quantity}\u00d7 {self.variant} (cart {self.cart_id})'

    @property
    def line_total_cents(self) -> int:
        return self.variant.price_cents * self.quantity


# =============================================================================
# Order (Sprint 3 creates, Sprint 4 transitions through Printify)
# =============================================================================

class Order(models.Model):
    """
    A paid order. Created by the Stripe checkout.session.completed webhook
    (Sprint 3). Submitted to Printify in Sprint 4. Status transitions through
    Printify webhooks track production and delivery.

    Customer identity is just `email` \u2014 guest checkout, no User FK.

    Money values are integer cents. Prices on OrderItem are snapshotted at
    order-creation time and never read back from Variant; historical orders
    must keep their prices even if the Variant later changes.
    """

    # Status lifecycle:
    #   paid              \u2192 webhook just landed; not yet sent to Printify (Sprint 3 default)
    #   submitted         \u2192 Printify accepted the order (Sprint 4)
    #   submission_failed \u2192 Printify rejected (bad address, OOS) (Sprint 4)
    #   in_production     \u2192 order:sent-to-production webhook (Sprint 4)
    #   shipped           \u2192 order:shipment:created webhook (Sprint 4)
    #   delivered         \u2192 order:shipment:delivered webhook (Sprint 4)
    #   canceled          \u2192 manual / refund flow (Sprint 5+)
    #   refunded          \u2192 manual / refund flow (Sprint 5+)
    STATUS_PAID = 'paid'
    STATUS_SUBMITTED = 'submitted'
    STATUS_SUBMISSION_FAILED = 'submission_failed'
    STATUS_IN_PRODUCTION = 'in_production'
    STATUS_SHIPPED = 'shipped'
    STATUS_DELIVERED = 'delivered'
    STATUS_CANCELED = 'canceled'
    STATUS_REFUNDED = 'refunded'
    STATUS_CHOICES = [
        (STATUS_PAID, 'Paid'),
        (STATUS_SUBMITTED, 'Submitted to Printify'),
        (STATUS_SUBMISSION_FAILED, 'Submission failed'),
        (STATUS_IN_PRODUCTION, 'In production'),
        (STATUS_SHIPPED, 'Shipped'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_CANCELED, 'Canceled'),
        (STATUS_REFUNDED, 'Refunded'),
    ]

    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='orders')
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_PAID,
        db_index=True,
    )

    # Contact
    email = models.EmailField(db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)

    # Shipping address (US only for v1)
    shipping_address_line_1 = models.CharField(max_length=200)
    shipping_address_line_2 = models.CharField(max_length=200, blank=True)
    shipping_city = models.CharField(max_length=100)
    shipping_state = models.CharField(max_length=20, help_text='Two-letter state code, e.g. "PA"')
    shipping_postal_code = models.CharField(max_length=20)
    shipping_country = models.CharField(max_length=2, default='US')

    # Money snapshots (all in integer cents)
    subtotal_cents = models.IntegerField(default=0)
    shipping_cents = models.IntegerField(default=0)
    tax_cents = models.IntegerField(default=0)
    total_cents = models.IntegerField(default=0)

    # Shipping selection — Printify wants an integer code (1 = standard, 2 = priority, etc).
    # Defaults to 1 (standard). We also keep the human-readable label.
    shipping_method_code = models.IntegerField(default=1)
    shipping_rate_label = models.CharField(max_length=100, blank=True, default='Standard shipping')

    # External IDs
    stripe_session_id = models.CharField(max_length=255, unique=True, db_index=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, db_index=True)
    printify_order_id = models.CharField(max_length=255, blank=True, db_index=True)

    # Fulfillment milestones (populated in Sprint 4)
    submitted_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    tracking_number = models.CharField(max_length=255, blank=True)
    tracking_url = models.URLField(max_length=500, blank=True)
    tracking_carrier = models.CharField(max_length=100, blank=True)

    # Submission failure detail
    submission_error = models.TextField(blank=True)

    # Email dedupe guards (Sprint 4) — belt-and-suspenders against a
    # customer-facing email going out twice. WebhookEvent's (source, event_id)
    # uniqueness is the primary defense against reprocessing a duplicate
    # delivery; these timestamps are the secondary guard, checked at the
    # point of sending in orders/emails.py so even a manual re-trigger or a
    # race in webhook processing can't double-send.
    confirmation_sent_at = models.DateTimeField(null=True, blank=True)
    shipped_email_sent_at = models.DateTimeField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['brand', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'Order #{self.pk} ({self.brand.domain}, {self.email})'

    @property
    def customer_name(self) -> str:
        return f'{self.first_name} {self.last_name}'.strip()


class OrderItem(models.Model):
    """
    A line item on an Order. All display fields are snapshots of the Variant
    at order-creation time \u2014 we never read prices, titles, or sizes back from
    the live Variant. This guarantees historical orders render correctly
    forever, even if the Variant is renamed or soft-deleted.

    `variant` is PROTECT'd so the FK can't dangle, but the Variant being
    soft-deleted (is_enabled=False) is fine \u2014 the OrderItem still references it.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name='order_items')

    # Snapshots at order time \u2014 immutable thereafter
    product_title = models.CharField(max_length=300)
    variant_title = models.CharField(max_length=200)
    variant_size = models.CharField(max_length=50, blank=True)
    variant_color = models.CharField(max_length=100, blank=True)

    quantity = models.PositiveIntegerField()
    unit_price_cents = models.IntegerField()
    line_total_cents = models.IntegerField()

    # Snapshot of the default image at order time so the receipt and order
    # detail pages don't depend on the live product. URL only \u2014 we don't
    # rehost Printify images.
    image_url = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.quantity}\u00d7 {self.product_title} \u2014 {self.variant_title}'
