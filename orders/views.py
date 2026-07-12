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
    POST /webhooks/printify/     printify_webhook (Sprint 4: HMAC verify, order + product handlers)
"""

from __future__ import annotations

import hashlib
import hmac
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
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from brands.models import Brand
from catalog.models import Product, Variant
from catalog.printify_client import PrintifyClient, PrintifyError
from catalog.services import sync_one_product

from .cart_utils import get_cart_or_none, get_or_create_cart
from .checkout_services import (
    SHIPPING_METHOD_STANDARD,
    configure_stripe,
    create_order_from_stripe_session,
    create_stripe_checkout_session,
    quote_shipping_for_cart,
    submit_order_to_printify,
)
from .emails import send_order_confirmation, send_order_shipped
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
# Sprint 5 adds charge.refunded so a dashboard-issued refund reflects onto the
# local Order (refunded_cents / refunded_at; a full refund flips status).
STRIPE_HANDLED_EVENT_TYPES = frozenset({
    'checkout.session.completed',
    'charge.refunded',
})

# Printify event types we actually process: four order:* events + three
# product:* events (Sprint 4 deliverables #4 and #5). Same rationale as
# STRIPE_HANDLED_EVENT_TYPES — everything else short-circuits to a 200
# without a WebhookEvent row or handler dispatch.
PRINTIFY_HANDLED_EVENT_TYPES = frozenset({
    'order:created',
    'order:sent-to-production',
    'order:shipment:created',
    'order:shipment:delivered',
    'product:publish:started',
    'product:publish:succeeded',
    'product:deleted',
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

    # Printify variant IDs are blueprint-level, not per-product: the same
    # printify_variant_id (e.g. "M / Black" on the Unisex Heavy Cotton Tee) is
    # shared by EVERY product built on that blueprint. So the lookup MUST be
    # scoped to the specific product, or .get() raises MultipleObjectsReturned
    # as soon as the brand has 2+ products on one blueprint. (product,
    # printify_variant_id) is unique_together, so scoping by product_id makes
    # the match exact. The add-to-cart button posts product_id (data-product-id).
    raw_product_id = (request.POST.get('product_id') or '').strip()
    if not raw_product_id:
        return HttpResponseBadRequest('product_id is required')
    try:
        product_id = int(raw_product_id)
    except ValueError:
        return HttpResponseBadRequest('product_id must be an integer')

    try:
        quantity = max(1, int(request.POST.get('quantity', 1)))
    except (TypeError, ValueError):
        quantity = 1

    # Variant must belong to this product AND brand, be enabled and available.
    try:
        variant = Variant.objects.select_related('product').get(
            product_id=product_id,
            printify_variant_id=printify_variant_id,
            product__brand=brand,
            is_enabled=True,
            is_available=True,
        )
    except Variant.DoesNotExist:
        logger.info(
            'cart_add: variant printify_id=%s not available for product=%s brand=%s',
            printify_variant_id, product_id, brand.domain,
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

    # Require the no-return-policy acknowledgment. The cart checkbox is marked
    # `required` (blocks the native submit in a normal browser); this is the
    # server-side backstop so a crafted POST can't skip it. The acceptance is
    # recorded on the Stripe session metadata (create_stripe_checkout_session)
    # as dispute/chargeback evidence.
    if not request.POST.get('agree_returns'):
        messages.warning(
            request,
            'Please confirm you\u2019ve read the no return policy before checking out.',
        )
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
# Public order lookup + status (Sprint 5)
# =============================================================================

@require_http_methods(['GET', 'POST'])
def order_lookup(request):
    """
    GET/POST /orders/lookup/ — find an order by number + email.

    On a successful match, redirect to the tokenized public status page. The
    lookup_token in the status URL is the capability; the (order number +
    email) pair here is just the lookup key, matched case-insensitively on
    email so we don't leak whether an order number exists to someone who
    doesn't also know the email on it.
    """
    brand = _require_brand(request)

    if request.method == 'GET':
        return render(request, 'orders/order_lookup.html', {})

    raw_order_number = (request.POST.get('order_number') or '').strip().lstrip('#')
    email = (request.POST.get('email') or '').strip()

    order = None
    if raw_order_number.isdigit() and email:
        order = (
            Order.objects
            .filter(pk=int(raw_order_number), brand=brand, email__iexact=email)
            .first()
        )

    if order is None:
        return render(request, 'orders/order_lookup.html', {
            'error': 'We couldn’t find an order with that number and email. '
                     'Double-check both and try again.',
            'values': {'order_number': raw_order_number, 'email': email},
        }, status=404)

    return redirect('orders:order_status', lookup_token=order.lookup_token)


@require_GET
def order_status(request, lookup_token):
    """
    GET /orders/status/<lookup_token>/ — public order status page.

    The unguessable token is the capability, so no login is required. 404 if
    the token doesn't match an order for this brand. The template sets
    noindex so these transactional URLs stay out of search results.
    """
    brand = _require_brand(request)
    order = Order.objects.filter(lookup_token=lookup_token, brand=brand).first()
    if order is None:
        raise Http404('No such order.')
    return render(request, 'orders/order_status.html', {'order': order})


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
        elif event_type == 'charge.refunded':
            _handle_charge_refunded(event['data']['object'])
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
    Materialize an Order from the Stripe checkout.session.completed event,
    send the confirmation email, and submit the order to Printify.

    `session_obj` is a Stripe object (post-construct_event); we call .to_dict()
    to get plain types before passing into checkout_services. v15+ of the
    stripe SDK changed StripeObject so it no longer inherits from dict, hence
    the explicit to_dict.

    Confirmation email fires before Printify submission is attempted: the
    customer paid, so they get a receipt regardless of what happens next in
    fulfillment. Both send_order_confirmation and submit_order_to_printify
    are internally idempotent (gated on Order timestamp/status fields), so
    if create_order_from_stripe_session returns a pre-existing Order (the
    dedup path), neither one double-fires.
    """
    if hasattr(session_obj, 'to_dict'):
        session_dict = session_obj.to_dict()
    else:
        session_dict = dict(session_obj)

    order = create_order_from_stripe_session(session_dict)
    if order is None:
        return

    send_order_confirmation(order)
    submit_order_to_printify(order)


def _handle_charge_refunded(charge_obj) -> None:
    """
    Reflect a Stripe refund onto the local Order (Sprint 5).

    Fired by the charge.refunded webhook. Matches the Order by
    stripe_payment_intent_id (the charge carries the payment_intent), records
    the cumulative amount Stripe reports refunded, and flips status to
    'refunded' only on a FULL refund — a partial refund records the amount but
    leaves the fulfillment status intact.

    Soft-skips (logs + returns) if no local Order matches the charge's
    payment_intent — e.g. a refund on a charge from some other integration
    sharing this Stripe account. Printify refunds are handled separately (a
    support ticket); see the admin note and Sprint 5 delivery notes.
    """
    if hasattr(charge_obj, 'to_dict'):
        charge = charge_obj.to_dict()
    else:
        charge = dict(charge_obj)

    payment_intent_id = charge.get('payment_intent') or ''
    if not payment_intent_id:
        logger.warning('charge.refunded with no payment_intent; cannot match an Order.')
        return

    order = Order.objects.filter(stripe_payment_intent_id=payment_intent_id).first()
    if order is None:
        logger.warning(
            'charge.refunded for payment_intent=%s matched no local Order; skipping.',
            payment_intent_id,
        )
        return

    amount_refunded = int(charge.get('amount_refunded') or 0)
    fully_refunded = bool(charge.get('refunded'))

    order.refunded_cents = amount_refunded
    order.refunded_at = timezone.now()
    update_fields = ['refunded_cents', 'refunded_at', 'updated_at']
    if fully_refunded:
        order.status = Order.STATUS_REFUNDED
        update_fields.append('status')
    order.save(update_fields=update_fields)

    logger.info(
        'Order #%d refunded (amount_refunded=%d cents, full=%s)',
        order.pk, amount_refunded, fully_refunded,
    )


# =============================================================================
# Printify webhook (Sprint 4: HMAC verification + real handler dispatch)
# =============================================================================

@csrf_exempt
@require_POST
def printify_webhook(request):
    """
    POST /webhooks/printify/

    Verifies the HMAC-SHA256 signature (header X-Pfy-Signature, format
    'sha256={hexdigest}'), dedupes against WebhookEvent (source=printify),
    and dispatches to a per-event-type handler.

    Returns 200 on success and on already-processed / ignored events; 403 on
    signature failure; 500 on processing failure (Printify will redeliver).
    """
    raw_body = request.body
    signature_header = request.META.get('HTTP_X_PFY_SIGNATURE', '')

    secret = settings.PRINTIFY_WEBHOOK_SECRET
    if not secret:
        logger.error('Printify webhook received but PRINTIFY_WEBHOOK_SECRET is empty.')
        return HttpResponse(status=500)

    expected_signature = 'sha256=' + hmac.new(
        secret.encode(), raw_body, hashlib.sha256,
    ).hexdigest()
    # hmac.compare_digest is timing-safe; a plain == leaks timing info that
    # can be used to forge a signature byte-by-byte.
    if not hmac.compare_digest(signature_header, expected_signature):
        logger.warning(
            'Printify webhook: signature verification failed (header=%r)',
            signature_header[:20],
        )
        return HttpResponse(status=403)

    try:
        payload = json.loads(raw_body or b'{}')
    except json.JSONDecodeError:
        logger.warning('Printify webhook: invalid JSON body (len=%d)', len(raw_body or b''))
        return HttpResponseBadRequest('Invalid JSON')

    raw_id = payload.get('id')
    event_id = str(raw_id) if raw_id is not None else f'no-id-{timezone.now().timestamp()}'
    event_type = str(payload.get('type', ''))[:100]

    # Skip events we don't process. No audit row, no handler dispatch --
    # mirrors the Stripe webhook's noise filter.
    if event_type not in PRINTIFY_HANDLED_EVENT_TYPES:
        logger.debug(
            'Printify webhook: ignoring event_type=%s id=%s',
            event_type, event_id,
        )
        return HttpResponse(status=200)

    # Idempotency -- same record-and-decide pattern as the Stripe webhook.
    record, created = WebhookEvent.objects.get_or_create(
        source=WebhookEvent.SOURCE_PRINTIFY,
        event_id=event_id,
        defaults={
            'event_type': event_type,
            'payload': payload,
        },
    )
    if not created:
        if record.processed_at is not None:
            logger.info('Printify webhook duplicate (already processed): %s', event_id)
            return HttpResponse(status=200)
        logger.info('Printify webhook re-processing previously failed event: %s', event_id)

    resource = payload.get('resource') or {}

    try:
        handler = _PRINTIFY_EVENT_HANDLERS.get(event_type)
        if handler:
            handler(resource)
        else:
            logger.info('Printify webhook: no handler for type=%s id=%s', event_type, event_id)
    except Exception as e:  # noqa: BLE001 -- log and 500 so Printify retries
        logger.exception('Printify webhook handler failed: %s', e)
        record.error = str(e)[:5000]
        record.save(update_fields=['error'])
        return HttpResponse(status=500)

    record.processed_at = timezone.now()
    record.error = ''
    record.save(update_fields=['processed_at', 'error'])
    return HttpResponse(status=200)


# -----------------------------------------------------------------------------
# Printify event handlers
#
# Each takes the `resource` dict from the webhook payload
# (payload['resource']). Order handlers look up the local Order by
# printify_order_id; product handlers look up the local Brand by
# printify_shop_id. Both soft-skip (log + return) rather than raise when the
# lookup misses, since raising would 500 the webhook and trigger a Printify
# retry storm for something that isn't a transient failure.
# -----------------------------------------------------------------------------

def _printify_shop_id(resource: dict) -> str:
    """
    Extract the Printify shop id from a webhook resource, coerced to str.

    Printify nests shop_id under resource['data'] and sends it as an int, not
    at the top level -- confirmed against a real product:publish:started
    payload. Fall back to a top-level key defensively in case a topic uses a
    flatter shape.
    """
    data = resource.get('data') or {}
    return str(data.get('shop_id') or resource.get('shop_id') or '')


def _handle_printify_order_created(resource: dict) -> None:
    """
    Logging only. We already have printify_order_id from the synchronous
    create_order() response in submit_order_to_printify -- this webhook is
    just Printify's own confirmation of receipt.
    """
    logger.info('Printify order:created resource id=%s', resource.get('id'))


def _handle_printify_order_in_production(resource: dict) -> None:
    printify_order_id = str(resource.get('id') or '')
    order = Order.objects.filter(printify_order_id=printify_order_id).first()
    if order is None:
        logger.warning(
            'order:sent-to-production for unknown printify_order_id=%s', printify_order_id,
        )
        return
    order.status = Order.STATUS_IN_PRODUCTION
    order.save(update_fields=['status', 'updated_at'])
    logger.info('Order #%d -> in_production', order.pk)
    # No customer email by default -- noisy per Sprint 4 default (confirmed
    # in prompt_sprint_4.md "when to ask, when to act").


def _handle_printify_order_shipped(resource: dict) -> None:
    printify_order_id = str(resource.get('id') or '')
    order = Order.objects.filter(printify_order_id=printify_order_id).first()
    if order is None:
        logger.warning(
            'order:shipment:created for unknown printify_order_id=%s', printify_order_id,
        )
        return

    # Printify's shipment payload shape isn't nailed down until we see a real
    # delivery, so this is deliberately defensive: try a `shipments` list
    # first (Printify's documented shape for multi-package orders), then fall
    # back to tracking fields directly on the resource.
    shipments = resource.get('shipments') or (resource.get('data') or {}).get('shipments') or []
    if shipments:
        first_shipment = shipments[0]
        tracking_number = first_shipment.get('number') or ''
        tracking_url = first_shipment.get('url') or ''
        carrier = first_shipment.get('carrier') or ''
    else:
        tracking_number = resource.get('tracking_number') or resource.get('number') or ''
        tracking_url = resource.get('tracking_url') or resource.get('url') or ''
        carrier = resource.get('carrier') or ''

    order.status = Order.STATUS_SHIPPED
    order.shipped_at = timezone.now()
    order.tracking_number = tracking_number
    order.tracking_url = tracking_url
    order.tracking_carrier = carrier
    order.save(update_fields=[
        'status', 'shipped_at', 'tracking_number', 'tracking_url',
        'tracking_carrier', 'updated_at',
    ])
    logger.info(
        'Order #%d -> shipped (carrier=%s tracking=%s)',
        order.pk, carrier, tracking_number,
    )
    send_order_shipped(order)


def _handle_printify_order_delivered(resource: dict) -> None:
    printify_order_id = str(resource.get('id') or '')
    order = Order.objects.filter(printify_order_id=printify_order_id).first()
    if order is None:
        logger.warning(
            'order:shipment:delivered for unknown printify_order_id=%s', printify_order_id,
        )
        return
    order.status = Order.STATUS_DELIVERED
    order.delivered_at = timezone.now()
    order.save(update_fields=['status', 'delivered_at', 'updated_at'])
    logger.info('Order #%d -> delivered', order.pk)
    # No customer email by default -- noisy per Sprint 4 default.


def _handle_printify_product_publish_started(resource: dict) -> None:
    """
    Fetch the product from Printify, sync it locally (reusing Sprint 3's
    sync_one_product), then call publishing_succeeded / publishing_failed so
    Printify unlocks the product card in their UI.

    Synchronous by design -- the webhook acknowledges only after the sync +
    callback completes. For a single product that's 2-3 Printify API calls
    plus a DB transaction, well under Printify's webhook timeout.
    """
    shop_id = _printify_shop_id(resource)
    product_id = str(resource.get('id') or '')

    brand = Brand.objects.filter(printify_shop_id=shop_id).first()
    if brand is None:
        # Shouldn't happen if webhook registration is per-brand, but a stray
        # or misconfigured subscription pointing at a shop we don't own
        # shouldn't 500 the webhook.
        logger.warning(
            'product:publish:started for unmapped shop_id=%s product_id=%s '
            '(no Brand has this printify_shop_id).',
            shop_id, product_id,
        )
        return

    client = PrintifyClient()
    try:
        product_data = client.get_product(shop_id, product_id)
        sync_one_product(brand, product_data)
        client.publishing_succeeded(shop_id, product_id)
    except Exception as exc:
        logger.exception(
            'product:publish:started sync failed for shop=%s product=%s',
            shop_id, product_id,
        )
        try:
            client.publishing_failed(shop_id, product_id, reason=str(exc)[:200])
        except Exception:
            logger.exception(
                'Also failed to call publishing_failed for shop=%s product=%s',
                shop_id, product_id,
            )
        raise  # let the outer handler log + record.error + return 500

    logger.info(
        'product:publish:started: synced + published product_id=%s for brand=%s',
        product_id, brand.domain,
    )


def _handle_printify_product_publish_succeeded(resource: dict) -> None:
    """Logging only -- our sync already ran in product:publish:started."""
    logger.info('product:publish:succeeded resource id=%s', resource.get('id'))


def _handle_printify_product_deleted(resource: dict) -> None:
    shop_id = _printify_shop_id(resource)
    product_id = str(resource.get('id') or '')
    updated = Product.objects.filter(
        brand__printify_shop_id=shop_id,
        printify_product_id=product_id,
    ).update(is_published=False)
    logger.info(
        'product:deleted shop=%s product=%s -> is_published=False (%d row(s))',
        shop_id, product_id, updated,
    )


_PRINTIFY_EVENT_HANDLERS = {
    'order:created': _handle_printify_order_created,
    'order:sent-to-production': _handle_printify_order_in_production,
    'order:shipment:created': _handle_printify_order_shipped,
    'order:shipment:delivered': _handle_printify_order_delivered,
    'product:publish:started': _handle_printify_product_publish_started,
    'product:publish:succeeded': _handle_printify_product_publish_succeeded,
    'product:deleted': _handle_printify_product_deleted,
}

