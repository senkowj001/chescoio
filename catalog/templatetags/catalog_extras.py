"""
Catalog template filters.

`cents`: format an integer-cent price as a $X.YY string. Used across product
list, product detail, and (Sprint 3+) cart and order templates so prices have
a single source of truth.
"""

from django import template

register = template.Library()


@register.filter(name='cents')
def cents_to_dollars(value):
    """
    Format an integer number of cents as a US dollar string with two decimals.

    Usage:
        {{ product.display_price_cents|cents }}   ->  "$24.00"

    Returns "—" for falsy or non-integer-coercible inputs so empty pricing
    doesn't render as "$0.00".
    """
    try:
        cents = int(value)
    except (TypeError, ValueError):
        return '—'
    if cents <= 0:
        return '—'
    return f'${cents / 100:.2f}'
