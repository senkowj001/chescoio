"""
Cart helpers — session resolution and cart get-or-create.

Centralized so cart views, the checkout view, and the Stripe webhook all
agree on what "the current cart" means.

Carts are session-keyed: one Cart per (brand, request.session.session_key).
If the session hasn't been issued yet (first visit, no cookie), we force-save
the session so we have a key to anchor the cart to.
"""

from __future__ import annotations

from typing import Optional

from django.http import HttpRequest

from brands.models import Brand
from .models import Cart


def ensure_session_key(request: HttpRequest) -> str:
    """
    Return the current request's session_key, creating a session if needed.

    Django's session machinery doesn't persist a session until something writes
    to it. The first add-to-cart needs a stable key, so we save() once if none
    exists yet.
    """
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def get_or_create_cart(request: HttpRequest, brand: Optional[Brand] = None) -> Cart:
    """
    Return the Cart for the current (brand, session) pair, creating it if
    it doesn't exist yet.

    `brand` defaults to `request.brand` (set by BrandMiddleware). Callers may
    override when they need to look up a cart for a specific brand (e.g. the
    Stripe webhook reading brand_id from session metadata).
    """
    brand = brand or getattr(request, 'brand', None)
    if brand is None:
        raise ValueError('get_or_create_cart called without a resolved Brand.')

    session_key = ensure_session_key(request)
    cart, _ = Cart.objects.get_or_create(
        brand=brand,
        session_key=session_key,
    )
    return cart


def get_cart_or_none(request: HttpRequest) -> Optional[Cart]:
    """
    Return the existing Cart for the current request, or None if none exists.

    Unlike get_or_create_cart, this is read-only and doesn't force-save the
    session \u2014 useful for header rendering on pages where we'd rather not
    set a session cookie for visitors who haven't done anything yet.
    """
    brand = getattr(request, 'brand', None)
    if brand is None:
        return None
    session_key = request.session.session_key
    if not session_key:
        return None
    return (
        Cart.objects
        .filter(brand=brand, session_key=session_key)
        .prefetch_related('items__variant__product__images')
        .first()
    )
