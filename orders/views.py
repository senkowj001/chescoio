"""
Orders views \u2014 cart, checkout, and inbound webhooks.

Sprint 3 ships:

  CART (session-keyed, HTMX-driven)
    GET  /cart/                  cart_page
    POST /cart/add/              cart_add
    POST /cart/items/<pk>/update cart_update_item
    POST /cart/items/<pk>/remove cart_remove_item
    GET  /cart/mini/             mini_cart        (HTMX fragment for header)
    POST /cart/shipping-quote/   cart_shipping_quote

  CHECKOUT
    POST /checkout/              checkout_start   (creates Stripe session, redirects)
    GET  /checkout/success/      checkout_success (poll-and-display)

  WEBHOOKS
    POST /webhooks/stripe/       stripe_webhook   (Sprint 3)
    POST /webhooks/printify/     printify_webhook (Sprint 2 stub; full in Sprint 4)
"""

from __future__ import annotations

import json
import logging
import time

import stripe
from django.conf import settings
from django.contrib import messages
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
)
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from catalog.models import Variant
from catalog.printify_client import PrintifyError

from .cart_utils import get_cart_or_none, get_or_create_cart
from .checkout_services import (
    SHIPPING_METHOD_STANDARD,
    configure_stripe,
    create_order_from_stripe_session,
    create_stripe_checkout_session,
    quote_shipping_for_cart,
)
from .models import Cart, CartItem, Order, WebhookEvent

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================

SESSION_KEY_SHIPPING_QUOTE = 'cart_shipping_quote'

# Polling budget on the checkout-success page. At 2 seconds per poll, 15
# attempts gives the Stripe webhook 30 seconds to materialize the local Order
# before the customer sees a timeout state. Generous enough for normal latency,
# tight enough to surface real misconfiguration (missing `stripe listen` in
# dev, broken webhook endpoint in prod) within half a minute.
CHECKOUT_SUCCESS_MAX_POLLS = 15

# Stripe event types we actually process. The Stripe firehose ships 7+ events
# per checkout (product.created, price.created, charge.succeeded,
# payment_intent.created/succeeded, charge.updated, plus the one we care
# about). Returning 200 early for everything else keeps WebhookEvent free of
# noise and avoids any chance of a serialization edge case on a payload shape
# we never look at causing a 500 that Stripe would then retry.
STRIPE_HANDLED_EVENT_TYPES = frozenset({
    'checkout.session.completed',
})


def _require_brand(request):
    """Raise 404 if BrandMiddleware didn't resolve a brand. View-level guard."""
    brand = getattr(request, 'brand', None)
    if brand is None:
        raise Http404('No brand resolved for this host.')
    return brand


def _is_htmx(request) -> bool:
    return request.headers.get('HX-Request') == 'true'


def _invalidate_shipping_quote(request) -> None:
    """Drop any cached shipping quote from the session (call after cart mutations)."""
    if SESSION_KEY_SHIPPING_QUOTE in request.session:
        del request.session[SESSION_KEY_SHIPPING_QUOTE]
        request.session.modified = True


def _get_cached_shipping_quote(request) -> dict | None:
    """
    Return the cached shipping quote dict if it's still fresh, else None.

    Quotes expire after settings.CART_SHIPPING_QUOTE_TTL_SECONDS so customers
    don't checkout with a stale rate.
    """
    quote = request.session.get(SESSION_KEY_SHIPPING_QUOTE)
    if not quote:
        return None
    age = time.time() - quote.get('cached_at', 0)
    if age > settings.CART_SHIPPING_QUOTE_TTL_SECONDS:
        return None
    return quote


def _render_cart_response(request, cart: Cart | None, *, status: int = 200) -> HttpResponse:
    """
    Render the cart contents fragment for HTMX (or full page for non-HTMX).

    The fragment includes an OOB swap for the header mini-cart so any cart
    mutation updates the count in one round trip. The full-page render does
    NOT include the OOB fragment — base.html's header already carries the
    canonical #mini-cart, and emitting a second one would be invalid HTML.
    """
    quote = _get_cached_shipping_quote(request)
    is_htmx_response = _is_htmx(request)
    ctx = {
        'cart': cart,
        'shipping_quote': quote,
        'total_with_shipping_cents': (
            (cart.subtotal_cents if cart else 0) + (quote['cents'] if quote else 0)
        ),
        'include_oob_minicart': is_htmx_response,
    }
    template = 'orders/_cart_contents.html' if is_htmx_response else 'orders/cart.html'
    return render(request, template, ctx, status=status)


# =============================================================================
# Cart views
# =============================================================================

@require_GET
def cart_page(request):
    """
    GET /cart/ \u2014 full cart page.
    """
    _require_brand(request)
    cart = get_cart_or_none(request)
    return _render_cart_response(request, cart)


@require_POST
def cart_add(request):
    """
    POST /cart/add/

    Form body:
        variant_id (str): the printify_variant_id of the variant to add
        quantity   (int, default=1): how many

    Returns the mini-cart fragment for the header (HTMX target).
    """
    brand = _require_brand(request)

    raw_variant_id = (request.POST.get('variant_id') or '').strip()
    if not raw_variant_id:
        return HttpResponseBadRequest('variant_id is required')
    try:
        printify_variant_id = int(raw_variant_id)
    except ValueError:
        return HttpResponseBadRequest('variant_id must be an integer')

    try:
        quantity = max(1, int(request.POST.get('quantity', 1)))
    except (TypeError, ValueError):
        quantity = 1

    # Variant must belong to this brand, be enabled and available.
    try:
        variant = Variant.objects.select_related('product').get(
            printify_variant_id=printify_variant_id,
            product__brand=brand,
            is_enabled=True,
            is_available=True,
        )
    except Variant.DoesNotExist:
        logger.info(
            'cart_add: variant printify_id=%s not available for brand=%s',
            printify_variant_id, brand.domain,
        )
        return HttpResponseBadRequest('That variant is no longer available.')

    cart = get_or_create_cart(request)
    item, created = CartItem.objects.get_or_create(
        cart=cart,
        variant=variant,
        defaults={'quantity': quantity},
    )
    if not created:
        item.quantity = item.quantity + quantity
        item.save(update_fields=['quantity', 'updated_at'])

    cart.save(update_fields=['updated_at'])  # bump updated_at on the parent
    _invalidate_shipping_quote(request)

    logger.info(
        'cart_add: cart=%d variant=%s qty=%d (now %d in cart)',
        cart.pk, variant.printify_variant_id, quantity, item.quantity,
    )

    return render(request, 'orders/_mini_cart.html', {'cart': cart})


@require_POST
def cart_update_item(request, item_pk):
    """
    POST /cart/items/<pk>/update

    Form body: quantity (positive int). 0 removes the item.
    """
    brand = _require_brand(request)
    cart = get_cart_or_none(request)
    if cart is None:
        return _render_cart_response(request, None)

    try:
        item = cart.items.select_related('variant__product').get(pk=item_pk)
    except CartItem.DoesNotExist:
        return _render_cart_response(request, cart, status=404)

    try:
        new_quantity = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        new_quantity = 1

    if new_quantity <= 0:
        item.delete()
    else:
        item.quantity = new_quantity
        item.save(update_fields=['quantity', 'updated_at'])

    cart.save(update_fields=['updated_at'])
    _invalidate_shipping_quote(request)

    # Refresh from DB after mutations.
    cart = get_cart_or_none(request)
    return _render_cart_response(request, cart)


@require_POST
def cart_remove_item(request, item_pk):
    """
    POST /cart/items/<pk>/remove
    """
    _require_brand(request)
    cart = get_cart_or_none(request)
    if cart is None:
        return _render_cart_response(request, None)

    cart.items.filter(pk=item_pk).delete()
    cart.save(update_fields=['updated_at'])
    _invalidate_shipping_quote(request)

    cart = get_cart_or_none(request)
    return _render_cart_response(request, cart)


@require_GET
def mini_cart(request):
    """
    GET /cart/mini/ \u2014 HTMX fragment for the header.
    """
    _require_brand(request)
    cart = get_cart_or_none(request)
    return render(request, 'orders/_mini_cart.html', {'cart': cart})


@require_POST
def cart_shipping_quote(request):
    """
    POST /cart/shipping-quote/

    Form body: postal_code (US ZIP)

    Calls Printify shipping rate API, caches result in session, re-renders cart.
    """
    _require_brand(request)
    cart = get_cart_or_none(request)
    if cart is None or not cart.items.exists():
        return _render_cart_response(request, cart)

    postal_code = (request.POST.get('postal_code') or '').strip()
    if not postal_code or len(postal_code) < 3:
        # Re-render the cart unchanged; the form template surfaces validation.
        ctx_extra = {'shipping_error': 'Enter a US ZIP code to see shipping rates.'}
        return _render_cart_with_error(request, cart, ctx_extra)

    try:
        quote = quote_shipping_for_cart(cart, postal_code, country='US')
    except PrintifyError as e:
        logger.warning('Shipping quote failed for cart=%d zip=%s: %s', cart.pk, postal_code, e)
        return _render_cart_with_error(request, cart, {
            'shipping_error': 'We couldn\u2019t calculate shipping for that ZIP. Please double-check it or try again.',
        })
    except ValueError as e:
        return _render_cart_with_error(request, cart, {'shipping_error': str(e)})

    # Cache in session. `raw` payload is dropped to keep the session small.
    quote_cached = {
        'method_code': quote['method_code'],
        'label': quote['label'],
        'cents': quote['cents'],
        'currency': quote['currency'],
        'postal_code': postal_code,
        'cached_at': time.time(),
    }
    request.session[SESSION_KEY_SHIPPING_QUOTE] = quote_cached
    request.session.modified = True

    return _render_cart_response(request, cart)


def _render_cart_with_error(request, cart, extra_ctx: dict):
    """Variant of _render_cart_response that surfaces a shipping_error."""
    quote = _get_cached_shipping_quote(request)
    is_htmx_response = _is_htmx(request)
    ctx = {
        'cart': cart,
        'shipping_quote': quote,
        'total_with_shipping_cents': (
            (cart.subtotal_cents if cart else 0) + (quote['cents'] if quote else 0)
        ),
        'include_oob_minicart': is_htmx_response,
        **extra_ctx,
    }
    template = 'orders/_cart_contents.html' if is_htmx_response else 'orders/cart.html'
    return render(request, template, ctx)


# =============================================================================
# Checkout
# =============================================================================

@require_POST
def checkout_start(request):
    """
    POST /checkout/

    Builds a Stripe Checkout Session and redirects the customer to Stripe.
    Requires a fresh shipping quote in session.
    """
    _require_brand(request)
    cart = get_cart_or_none(request)
    if cart is None or not cart.items.exists():
        messages.warning(request, 'Your cart is empty.')
        return redirect('orders:cart_page')

    quote = _get_cached_shipping_quote(request)
    if quote is None:
        messages.warning(request, 'Please enter a ZIP code to calculate shipping before checking out.')
        return redirect('orders:cart_page')

    if not settings.STRIPE_SECRET_KEY:
        logger.error('checkout_start: STRIPE_SECRET_KEY is not configured.')
        messages.error(request, 'Checkout is temporarily unavailable. Please try again shortly.')
        return redirect('orders:cart_page')

    try:
        session = create_stripe_checkout_session(request, cart, quote)
    except stripe.error.StripeError as e:
        logger.exception('Stripe Checkout creation failed: %s', e)
        messages.error(request, 'We couldn\u2019t start the checkout. Please try again.')
        return redirect('orders:cart_page')

    return HttpResponseRedirect(session.url)


@require_GET
def checkout_success(request):
    """
    GET /checkout/success/?session_id=cs_test_...

    Order may or may not be persisted yet \u2014 the Stripe webhook is the creator,
    and may land a few seconds after the redirect. We render a "processing"
    state that polls via HTMX, then swaps in the real Order detail.
    """
    _require_brand(request)
    session_id = request.GET.get('session_id', '').strip()
    if not session_id:
        return redirect('catalog:product_list')

    order = Order.objects.filter(stripe_session_id=session_id).first()

    try:
        attempt = int(request.GET.get('attempt', 0))
    except (TypeError, ValueError):
        attempt = 0
    attempt = max(0, attempt)
    timed_out = order is None and attempt >= CHECKOUT_SUCCESS_MAX_POLLS

    ctx = {
        'session_id': session_id,
        'order': order,
        'attempt': attempt,
        'next_attempt': attempt + 1,
        'timed_out': timed_out,
    }

    # HTMX poll fragment vs. full page.
    if _is_htmx(request):
        return render(request, 'orders/_checkout_success_status.html', ctx)
    return render(request, 'orders/checkout_success.html', ctx)


# =============================================================================
# Stripe webhook
# =============================================================================

@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    POST /webhooks/stripe/

    Verifies the Stripe signature, dedupes against WebhookEvent (source=stripe),
    and on checkout.session.completed creates the local Order + OrderItems.

    Returns 200 on success and on already-processed events; 400 on signature
    failure; 500 on processing failure (Stripe will retry).
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error('Stripe webhook received but STRIPE_WEBHOOK_SECRET is empty.')
        return HttpResponse(status=500)

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        logger.warning('Stripe webhook: invalid payload')
        return HttpResponseBadRequest('Invalid payload')
    except stripe.error.SignatureVerificationError:
        logger.warning('Stripe webhook: signature verification failed')
        return HttpResponse(status=400)

    event_id = event['id']
    event_type = event['type']

    # Skip events we don't process. No audit row, no handler dispatch.
    if event_type not in STRIPE_HANDLED_EVENT_TYPES:
        logger.debug(
            'Stripe webhook: ignoring event_type=%s id=%s',
            event_type, event_id,
        )
        return HttpResponse(status=200)

    # Idempotency \u2014 record-and-decide. Using get_or_create with the
    # (source, event_id) uniqueness gives us the right race semantics: only
    # the first webhook delivery for a given id creates the row.
    record, created = WebhookEvent.objects.get_or_create(
        source=WebhookEvent.SOURCE_STRIPE,
        event_id=event_id,
        defaults={
            'event_type': event_type,
            'payload': event.to_dict(),
        },
    )
    if not created:
        # Already seen. If we previously processed it, return 200 immediately;
        # if we crashed mid-processing, leave the row as-is and let Stripe
        # retry hit us again (we'll fall through to the handler below).
        if record.processed_at is not None:
            logger.info('Stripe webhook duplicate (already processed): %s', event_id)
            return HttpResponse(status=200)
        logger.info('Stripe webhook re-processing previously failed event: %s', event_id)

    try:
        if event_type == 'checkout.session.completed':
            _handle_checkout_completed(event['data']['object'])
        else:
            logger.info('Stripe webhook: no handler for type=%s id=%s', event_type, event_id)
    except Exception as e:  # noqa: BLE001 \u2014 we want to log and 500 so Stripe retries
        logger.exception('Stripe webhook handler failed: %s', e)
        record.error = str(e)[:5000]
        record.save(update_fields=['error'])
        return HttpResponse(status=500)

    record.processed_at = timezone.now()
    record.error = ''
    record.save(update_fields=['processed_at', 'error'])
    return HttpResponse(status=200)


def _handle_checkout_completed(session_obj) -> None:
    """
    Materialize an Order from the Stripe checkout.session.completed event.

    `session_obj` is a Stripe object (post-construct_event); we call .to_dict()
    to get plain types before passing into checkout_services. v15+ of the
    stripe SDK changed StripeObject so it no longer inherits from dict, hence
    the explicit to_dict.
    """
    if hasattr(session_obj, 'to_dict'):
        session_dict = session_obj.to_dict()
    else:
        session_dict = dict(session_obj)

    create_order_from_stripe_session(session_dict)


# =============================================================================
# Printify webhook (Sprint 2 stub; Sprint 4 wires real handlers + HMAC verify)
# =============================================================================

@csrf_exempt
@require_POST
def printify_webhook(request):
    """
    POST /webhooks/printify/

    Sprint 2 stub: parses JSON, dedupes on (source=printify, event_id),
    persists the payload to WebhookEvent, returns 200. No business logic
    is applied yet \u2014 Sprint 4 adds:
      - HMAC signature verification against settings.PRINTIFY_WEBHOOK_SECRET
        (header: X-Pfy-Signature, format 'sha256={hexdigest}')
      - Per-event-type handler dispatch (orders + product publish events)
      - Calling Printify's publishing_succeeded / publishing_failed endpoint
        after a product:publish:started event
      - Idempotent webhook registration via a management command
    """
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        logger.warning('Printify webhook: invalid JSON body (len=%d)', len(request.body or b''))
        return HttpResponseBadRequest('Invalid JSON')

    raw_id = payload.get('id')
    event_id = str(raw_id) if raw_id is not None else f'no-id-{timezone.now().timestamp()}'
    event_type = str(payload.get('type', ''))[:100]

    obj, created = WebhookEvent.objects.get_or_create(
        source=WebhookEvent.SOURCE_PRINTIFY,
        event_id=event_id,
        defaults={
            'event_type': event_type,
            'payload': payload,
        },
    )

    if created:
        logger.info('Printify webhook recorded: type=%s id=%s', event_type, event_id)
    else:
        logger.info('Printify webhook duplicate ignored: type=%s id=%s', event_type, event_id)

    return HttpResponse(status=200)
