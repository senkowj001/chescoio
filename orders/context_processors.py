"""
Template context processors for the orders app.

Wired in via TEMPLATES.OPTIONS.context_processors in chescoio/settings/base.py.
"""

from __future__ import annotations

from .cart_utils import get_cart_or_none


def cart(request):
    """
    Inject the current visitor's Cart (or None) into every template context
    so the header mini-cart renders with the correct item count on the
    initial page load, before any HTMX interaction.

    Cheap: returns None without querying the DB for visitors who have no
    session key yet. For visitors with a session, runs a single SELECT
    with prefetched line items.
    """
    return {'cart': get_cart_or_none(request)}
