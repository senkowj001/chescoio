"""
Catalog views — product listing and detail pages.

All queries are scoped to request.brand (set by BrandMiddleware). Variants
and images are prefetched to avoid N+1 queries on the listing grid.
"""

from django.http import Http404
from django.shortcuts import render

from .models import Product


# Canonical apparel size order. Lower index = smaller size. Sizes not in this
# map (e.g. numeric sizes like "6" / "8" / "10" for women's apparel, or "One
# Size" for hats) fall through to a secondary sort that tries int() and then
# alphabetical — see _sort_sizes below.
_APPAREL_SIZE_ORDER = {
    label: idx for idx, label in enumerate([
        'XXS', 'XS', 'S', 'M', 'L', 'XL',
        '2XL', 'XXL',          # both spellings exist in Printify catalogs
        '3XL', 'XXXL',
        '4XL', 'XXXXL',
        '5XL', '6XL',
    ])
}


def _sort_sizes(sizes: list[str]) -> list[str]:
    """
    Return sizes sorted in apparel-canonical order.

    Sort key tiers, in order of precedence:
      0: Known apparel labels (XS, S, M, ..., 6XL) — use _APPAREL_SIZE_ORDER
      1: Numeric labels ("6", "8", "10") — sort numerically, larger than tier 0
      2: Anything else ("One Size", "Standard") — alphabetical, after numerics

    The composite tuple key makes Python's stable sort do the right thing.
    """
    def key(label: str):
        if label in _APPAREL_SIZE_ORDER:
            return (0, _APPAREL_SIZE_ORDER[label], label)
        try:
            return (1, float(label), label)
        except (TypeError, ValueError):
            return (2, 0, label.lower())
    return sorted(sizes, key=key)


def product_list(request):
    """
    /shop/ — grid of all published products for the current brand.
    """
    if not getattr(request, 'brand', None):
        raise Http404

    products = (
        Product.objects
        .filter(brand=request.brand, is_published=True)
        .prefetch_related('images', 'variants')
        .order_by('sort_order', 'title')
    )

    return render(request, 'catalog/product_list.html', {
        'products': products,
    })


def product_detail(request, slug):
    """
    /shop/<slug>/ — product detail page with variant selector.

    `variants_data` is a Python list that the template renders via
    {% raw %}{{ variants_data|json_script:"variants-data" }}{% endraw %}; the
    page script reads that <script> tag to coordinate size/color availability
    and update displayed price.
    """
    if not getattr(request, 'brand', None):
        raise Http404

    try:
        product = (
            Product.objects
            .prefetch_related('variants', 'images')
            .get(brand=request.brand, slug=slug, is_published=True)
        )
    except Product.DoesNotExist:
        raise Http404

    # Only enabled variants are interactable; disabled ones are excluded
    # entirely from the picker. is_available=False variants are still shown
    # but visually grayed out (out of stock vs. retired).
    variants = list(product.variants.filter(is_enabled=True).order_by('size', 'color'))

    # Build size/color option lists, deduped while preserving first-seen order.
    sizes: list[str] = []
    colors: list[str] = []
    for v in variants:
        if v.size and v.size not in sizes:
            sizes.append(v.size)
        if v.color and v.color not in colors:
            colors.append(v.color)

    # Sizes need apparel-canonical order (XS, S, M, L, XL, 2XL, ...) not
    # alphabetical (which gives "2XL, 3XL, L, M, S, XL, XS"). Colors stay in
    # Printify-return order — they have no canonical ordering and Printify's
    # order roughly matches design intent.
    sizes = _sort_sizes(sizes)

    # Plain Python list — the template uses |json_script to render this as
    # a safely-escaped <script type="application/json"> tag.
    variants_data = [
        {
            'id': v.printify_variant_id,
            'pk': v.pk,
            'size': v.size,
            'color': v.color,
            'price_cents': v.price_cents,
            'is_available': v.is_available,
            'sku': v.sku,
        }
        for v in variants
    ]

    return render(request, 'catalog/product_detail.html', {
        'product': product,
        'variants': variants,
        'sizes': sizes,
        'colors': colors,
        'variants_data': variants_data,
        'default_image': product.default_image,
    })
