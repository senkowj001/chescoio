"""
Checkout services \u2014 Stripe Checkout session creation, Printify shipping rate
quoting, and Order materialization from a completed Stripe session.

Kept separate from views.py so the logic is testable in isolation and the
view layer stays thin.

Sprint 3 scope:
  - quote_shipping_for_cart: call Printify shipping rates API for a cart + ZIP
  - create_stripe_checkout_session: build the Checkout Session with line items,
    shipping, Stripe Tax
  - create_order_from_stripe_session: from a completed Stripe session, create
    the local Order + OrderItems with snapshotted prices

Sprint 4 will add:
  - submit_order_to_printify (Order \u2192 Printify Orders API)
"""

from __future__ import annotations

import logging
from typing import Optional

import stripe
from django.conf import settings
from django.db import transaction
from django.urls import reverse

from brands.models import Brand
from catalog.printify_client import PrintifyClient, PrintifyError
from .models import Cart, Order, OrderItem

logger = logging.getLogger(__name__)


# =============================================================================
# Printify shipping rates
# =============================================================================

# v1 ships standard shipping only. Printify returns rates keyed by method
# in the calculate_shipping response; we surface the cheapest available rate
# and label it as standard. Express / priority are a 2.0 concern.
SHIPPING_METHOD_STANDARD = 1


def quote_shipping_for_cart(
    cart: Cart,
    postal_code: str,
    *,
    country: str = 'US',
    client: Optional[PrintifyClient] = None,
) -> dict:
    """
    Quote shipping from Printify for the given cart + ZIP.

    Returns a dict with at least:
        {
            'method_code': 1,
            'label': 'Standard shipping',
            'cents': 499,
            'currency': 'usd',
            'raw': {...}  # full Printify response, for debugging
        }

    Raises PrintifyError on API failure (caller decides whether to surface
    the error to the user or fall back to a flat-rate guess).
    """
    if not cart.brand.printify_shop_id:
        raise PrintifyError(
            f'Brand {cart.brand.name} has no printify_shop_id; cannot quote shipping.'
        )

    line_items = []
    for item in cart.items.all():
        line_items.append({
            'product_id': item.variant.product.printify_product_id,
            'variant_id': item.variant.printify_variant_id,
            'quantity': item.quantity,
        })

    if not line_items:
        raise ValueError('Cannot quote shipping for an empty cart.')

    address = {
        'country': country.upper(),
        'zip': postal_code,
    }

    client = client or PrintifyClient()
    resp = client.calculate_shipping(cart.brand.printify_shop_id, address, line_items)

    # Printify's shipping endpoint returns rate amounts keyed by method name
    # (e.g. {"standard": 499, "express": 999, ...}). The exact keys vary by
    # print provider and product type. We pull standard if present, otherwise
    # the cheapest numeric value we find.
    cents = _extract_standard_rate_cents(resp)
    if cents is None:
        raise PrintifyError(
            f'Could not extract a shipping rate from Printify response: {resp}'
        )

    return {
        'method_code': SHIPPING_METHOD_STANDARD,
        'label': 'Standard shipping',
        'cents': cents,
        'currency': 'usd',
        'raw': resp,
    }


def _extract_standard_rate_cents(resp: dict) -> Optional[int]:
    """
    Pull a shipping rate (in cents) out of the Printify response.

    Printify's response shape varies; the most common form is a flat dict of
    method-name -> cents:
        {"standard": 499, "priority": 749, "express": 1349}

    Some providers return a nested {"shipping_rates": [...]} structure. Be
    defensive and accept both.

    Strategy: prefer "standard" if present; otherwise pick the smallest int
    we can find amongst the values. Return None if nothing parseable.
    """
    if not isinstance(resp, dict):
        return None

    # Flat shape: {"standard": 499, ...}
    if 'standard' in resp and isinstance(resp['standard'], (int, float)):
        return int(resp['standard'])

    numeric_values = [
        int(v) for v in resp.values()
        if isinstance(v, (int, float)) and v > 0
    ]
    if numeric_values:
        return min(numeric_values)

    # Nested shape (less common): {"shipping_rates": [{"cost": 499, ...}]}
    rates = resp.get('shipping_rates') or resp.get('rates')
    if isinstance(rates, list) and rates:
        costs = []
        for r in rates:
            if not isinstance(r, dict):
                continue
            for key in ('cost', 'amount', 'price'):
                v = r.get(key)
                if isinstance(v, (int, float)) and v > 0:
                    costs.append(int(v))
                    break
        if costs:
            return min(costs)

    return None


# =============================================================================
# Stripe Checkout Session
# =============================================================================

def configure_stripe() -> None:
    """Set the module-level Stripe API key. Called by each entry point."""
    stripe.api_key = settings.STRIPE_SECRET_KEY


def create_stripe_checkout_session(
    request,
    cart: Cart,
    shipping_quote: dict,
) -> stripe.checkout.Session:
    """
    Create a Stripe Checkout Session for the given cart + shipping quote.

    `shipping_quote` is the dict returned by quote_shipping_for_cart (so the
    rate the customer saw on the cart page matches what Stripe charges).

    Stripe Tax is enabled (`automatic_tax.enabled=True`) so PA clothing
    exemption applies automatically when the PA registration is in place.

    Returns the Stripe Session object; the caller redirects to session.url.
    """
    configure_stripe()
    brand = cart.brand

    line_items = []
    for item in cart.items.all():
        variant = item.variant
        product = variant.product
        default_image = product.default_image
        image_urls = [default_image.url] if default_image else []

        # Stripe rejects descriptions longer than 500 chars and product_data
        # 'name' longer than 250. Trim defensively.
        product_name = product.title[:240] or f'Product {product.pk}'
        description = variant.title[:480] if variant.title else None

        product_data: dict = {
            'name': product_name,
            'metadata': {
                'variant_pk': str(variant.pk),
                'printify_variant_id': str(variant.printify_variant_id),
                'printify_product_id': product.printify_product_id,
            },
        }
        if description:
            product_data['description'] = description
        if image_urls:
            product_data['images'] = image_urls

        line_items.append({
            'price_data': {
                'currency': 'usd',
                'unit_amount': variant.price_cents,
                'tax_behavior': 'exclusive',
                'product_data': product_data,
            },
            'quantity': item.quantity,
        })

    shipping_options = [{
        'shipping_rate_data': {
            'type': 'fixed_amount',
            'display_name': shipping_quote['label'],
            'fixed_amount': {
                'amount': shipping_quote['cents'],
                'currency': shipping_quote['currency'],
            },
            'tax_behavior': 'exclusive',
        },
    }]

    success_url = (
        request.build_absolute_uri(reverse('orders:checkout_success'))
        + '?session_id={CHECKOUT_SESSION_ID}'
    )
    cancel_url = request.build_absolute_uri(reverse('orders:cart_page'))

    session = stripe.checkout.Session.create(
        mode='payment',
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        automatic_tax={'enabled': True},
        shipping_address_collection={'allowed_countries': ['US']},
        shipping_options=shipping_options,
        phone_number_collection={'enabled': True},
        customer_creation='if_required',
        metadata={
            'brand_id': str(brand.pk),
            'cart_id': str(cart.pk),
            'shipping_method_code': str(shipping_quote['method_code']),
            'shipping_label': shipping_quote['label'],
        },
    )
    logger.info(
        'Stripe Checkout Session created: id=%s brand=%s cart=%s amount_cents=%s',
        session.id, brand.domain, cart.pk, sum(li['price_data']['unit_amount'] * li['quantity'] for li in line_items),
    )
    return session


# =============================================================================
# Order materialization from Stripe webhook
# =============================================================================

@transaction.atomic
def create_order_from_stripe_session(session: dict) -> Optional[Order]:
    """
    Build an Order + OrderItems from a Stripe checkout.session.completed event.

    Idempotent: if an Order with this session.id already exists, returns it.
    The Stripe webhook handler also dedupes via WebhookEvent, but this is a
    second safety net.

    `session` is the dict-shaped Stripe session object (after .to_dict() in
    the webhook handler). The function reads:
      - id (session id)
      - payment_intent
      - amount_subtotal, amount_total, total_details.amount_tax, total_details.amount_shipping
      - customer_details.email, customer_details.name, customer_details.phone
      - shipping_details.address {...}
      - metadata.brand_id, metadata.cart_id, metadata.shipping_method_code, metadata.shipping_label

    Returns None (without raising) for sessions that are missing our own
    metadata keys (brand_id / cart_id) — these are synthetic events from
    `stripe trigger` or sessions created by something other than our own
    checkout flow. Raising would cause Stripe to retry indefinitely, which
    creates a retry storm with no recovery path.

    Raises ValueError if metadata is present but references a brand or cart
    that no longer exists — that's a real consistency issue worth a 500 + retry.
    """
    stripe_session_id = session['id']

    # Idempotency
    existing = Order.objects.filter(stripe_session_id=stripe_session_id).first()
    if existing:
        logger.info(
            'Order already exists for stripe session %s (order #%d); skipping.',
            stripe_session_id, existing.pk,
        )
        return existing

    metadata = session.get('metadata') or {}
    brand_id = metadata.get('brand_id')
    cart_id = metadata.get('cart_id')
    shipping_method_code = int(metadata.get('shipping_method_code') or SHIPPING_METHOD_STANDARD)
    shipping_label = metadata.get('shipping_label') or 'Standard shipping'

    # Sessions we didn't create won't have our metadata. Examples: synthetic
    # `stripe trigger` events, or sessions created by external tools sharing
    # the same webhook endpoint. Soft-skip so Stripe doesn't retry forever.
    if not brand_id or not cart_id:
        logger.warning(
            'Stripe session %s missing brand_id/cart_id metadata; not ours, '
            'skipping order creation. metadata=%r',
            stripe_session_id, dict(metadata),
        )
        return None

    try:
        brand = Brand.objects.get(pk=brand_id)
    except Brand.DoesNotExist:
        raise ValueError(f'Stripe session {stripe_session_id} has unknown brand_id={brand_id!r}')

    cart = Cart.objects.filter(pk=cart_id, brand=brand).prefetch_related(
        'items__variant__product__images'
    ).first()
    if cart is None or not cart.items.exists():
        # Cart was already consumed or deleted; we can still create the order
        # from the Stripe line items, but for v1 we treat this as an error
        # to investigate manually. A re-delivery of the webhook AFTER cart
        # cleanup would hit the idempotency check above first.
        raise ValueError(
            f'Cart {cart_id} for Stripe session {stripe_session_id} is missing or empty.'
        )

    customer = session.get('customer_details') or {}
    email = customer.get('email') or ''
    full_name = (customer.get('name') or '').strip()
    first_name, _, last_name = full_name.partition(' ')
    phone = customer.get('phone') or ''

    shipping = session.get('shipping_details') or {}
    addr = (shipping.get('address') or {})

    total_details = session.get('total_details') or {}

    order = Order.objects.create(
        brand=brand,
        status=Order.STATUS_PAID,
        email=email,
        first_name=first_name or 'Customer',
        last_name=last_name,
        phone=phone,
        shipping_address_line_1=addr.get('line1') or '',
        shipping_address_line_2=addr.get('line2') or '',
        shipping_city=addr.get('city') or '',
        shipping_state=addr.get('state') or '',
        shipping_postal_code=addr.get('postal_code') or '',
        shipping_country=(addr.get('country') or 'US').upper()[:2],
        subtotal_cents=int(session.get('amount_subtotal') or 0),
        shipping_cents=int(total_details.get('amount_shipping') or 0),
        tax_cents=int(total_details.get('amount_tax') or 0),
        total_cents=int(session.get('amount_total') or 0),
        shipping_method_code=shipping_method_code,
        shipping_rate_label=shipping_label,
        stripe_session_id=stripe_session_id,
        stripe_payment_intent_id=session.get('payment_intent') or '',
    )

    # Snapshot every cart line into OrderItems.
    for item in cart.items.all():
        variant = item.variant
        product = variant.product
        default_image = product.default_image
        OrderItem.objects.create(
            order=order,
            variant=variant,
            product_title=product.title,
            variant_title=variant.title,
            variant_size=variant.size,
            variant_color=variant.color,
            quantity=item.quantity,
            unit_price_cents=variant.price_cents,
            line_total_cents=variant.price_cents * item.quantity,
            image_url=default_image.url if default_image else '',
        )

    # Drop the cart \u2014 the order owns the data now. Use .delete() not items.delete()
    # so the Cart row itself goes away (the (brand, session_key) unique
    # constraint would otherwise prevent the customer's next session from
    # starting fresh on the same session cookie).
    cart.delete()

    logger.info(
        'Created Order #%d from Stripe session %s (brand=%s, total=%d cents)',
        order.pk, stripe_session_id, brand.domain, order.total_cents,
    )
    return order
