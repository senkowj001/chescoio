"""
Catalog views — product listing and detail pages.

All queries are scoped to request.brand (set by BrandMiddleware). Variants
and images are prefetched to avoid N+1 queries on the listing grid.
"""

from django.http import Http404
from django.shortcuts import render

from .models import Product


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

    # Build size/color option lists, preserving first-seen order so they
    # display in the same order Printify uses.
    sizes: list[str] = []
    colors: list[str] = []
    for v in variants:
        if v.size and v.size not in sizes:
            sizes.append(v.size)
        if v.color and v.color not in colors:
            colors.append(v.color)

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
