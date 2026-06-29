"""
Catalog sync services.

This module contains the *logic* of syncing a Printify shop into the local
catalog, decoupled from any specific entry point:

  - The `sync_printify_products` management command (cron / Heroku Scheduler)
  - The Django admin "Sync Now" action on a Brand (Sprint 3)
  - The Printify product:publish:started webhook handler (Sprint 4)

Two public entry points:

  sync_brand_catalog(brand, *, dry_run=False, limit_pages=None) -> dict
      Iterates all pages of Printify products for a brand and upserts them.
      Returns a stats dict. Logs via the module logger; no stdout/stderr.

  sync_one_product(brand, product_data) -> tuple[Product, str]
      Upsert one product + its variants + its images. Returns the Product and
      either 'created' or 'updated'. Used by Sprint 4's
      product:publish:started webhook handler to refresh a single product
      without re-walking the whole catalog. Transactional per-product.

Everything is idempotent: re-running yields the same result.
"""

import logging
from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from brands.models import Brand
from catalog.models import Product, ProductImage, Variant
from catalog.printify_client import PrintifyClient, PrintifyError

logger = logging.getLogger(__name__)


# =============================================================================
# Public entry points
# =============================================================================

def sync_brand_catalog(
    brand: Brand,
    *,
    dry_run: bool = False,
    limit_pages: int | None = None,
    client: PrintifyClient | None = None,
) -> dict:
    """
    Sync every Printify product for `brand` into the local catalog.

    Returns a stats dict with keys:
        pages, products_seen, products_created, products_updated, products_failed,
        variants_seen, variants_created, variants_updated, variants_disabled,
        images_replaced

    Raises:
        ValueError: brand has no printify_shop_id.
        PrintifyError: a fatal Printify API failure (rate-limited beyond retries,
            unrecoverable 5xx, etc). Per-product failures are logged and counted
            in stats['products_failed'] but do not abort the run.
    """
    if not brand.printify_shop_id:
        raise ValueError(
            f'Brand {brand.name} ({brand.domain}) has no printify_shop_id. '
            f'Set it via Django admin before running sync.'
        )

    if client is None:
        client = PrintifyClient()

    stats = _new_stats()
    page = 1

    logger.info(
        'sync_brand_catalog start: brand=%s shop=%s dry_run=%s',
        brand.domain, brand.printify_shop_id, dry_run,
    )

    while True:
        resp = client.list_products(brand.printify_shop_id, page=page, limit=50)
        products = resp.get('data') or []
        stats['pages'] += 1
        logger.info('  page %d: %d products', page, len(products))

        for printify_product in products:
            stats['products_seen'] += 1
            pid = printify_product.get('id', '?')
            if dry_run:
                continue
            try:
                _, result = sync_one_product(brand, printify_product, stats=stats)
                if result == 'created':
                    stats['products_created'] += 1
                elif result == 'updated':
                    stats['products_updated'] += 1
            except Exception as e:  # noqa: BLE001 — log and continue
                stats['products_failed'] += 1
                logger.exception(
                    'Failed to sync Printify product %s for brand %s: %s',
                    pid, brand.domain, e,
                )

        if not resp.get('next_page_url'):
            break
        page += 1
        if limit_pages and page > limit_pages:
            logger.info('Stopping at limit_pages=%d', limit_pages)
            break

    logger.info(
        'sync_brand_catalog done: brand=%s stats=%s',
        brand.domain, stats,
    )
    return stats


def sync_one_product(
    brand: Brand,
    data: dict,
    *,
    stats: dict | None = None,
) -> tuple[Product, str]:
    """
    Upsert one Printify product + its variants + its images for `brand`.

    Returns (product, 'created' | 'updated').

    All-or-nothing per product: the database changes are wrapped in a single
    transaction so a partial failure does not leave inconsistent rows.

    Used by:
      - sync_brand_catalog (the orchestrator above)
      - Sprint 4 product:publish:started webhook handler (single-product sync
        without re-walking the whole catalog)

    `stats` is optional. When provided, the same counters that
    sync_brand_catalog uses are incremented for variant / image work; callers
    that don't care can pass None.
    """
    return _sync_one_product_inner(brand, data, stats if stats is not None else _new_stats())


# =============================================================================
# Internals
# =============================================================================

def _new_stats() -> dict:
    return {
        'pages': 0,
        'products_seen': 0,
        'products_created': 0,
        'products_updated': 0,
        'products_failed': 0,
        'variants_seen': 0,
        'variants_created': 0,
        'variants_updated': 0,
        'variants_disabled': 0,
        'images_replaced': 0,
    }


@transaction.atomic
def _sync_one_product_inner(brand: Brand, data: dict, stats: dict) -> tuple[Product, str]:
    printify_product_id = str(data['id'])
    title = (data.get('title') or '').strip() or f'Untitled {printify_product_id}'
    description = data.get('description') or ''
    tags = data.get('tags') or []
    blueprint_id = data.get('blueprint_id') or 0
    print_provider_id = data.get('print_provider_id') or 0
    is_visible = bool(data.get('visible', True))

    # ---- Option map: option_value_id (int) -> (kind, value_str) -------------
    # Printify product.options:
    #   [{"name": "Size",  "type": "size",  "values": [{"id": 14, "title": "S"}, ...]},
    #    {"name": "Color", "type": "color", "values": [{"id": 1,  "title": "Black"}, ...]}]
    # Variant.options is then a list of value-ids, e.g. [14, 1] = "S / Black".
    option_value_map: dict[int, tuple[str, str]] = {}
    for opt in data.get('options') or []:
        kind = (opt.get('type') or opt.get('name') or '').lower()
        for v in opt.get('values') or []:
            vid = v.get('id')
            if vid is None:
                continue
            option_value_map[int(vid)] = (kind, str(v.get('title', '')))

    # ---- Slug: stable on update, unique-within-brand on create --------------
    existing = Product.objects.filter(printify_product_id=printify_product_id).first()
    if existing:
        slug = existing.slug
    else:
        slug = _unique_slug_for_brand(brand, title, printify_product_id)

    # ---- Compute base_retail_price_cents from cheapest enabled variant ------
    printify_variants = data.get('variants') or []
    enabled_prices = [
        int(v.get('price', 0))
        for v in printify_variants
        if v.get('is_enabled', True) and v.get('is_available', True)
    ]
    base_price_cents = min(enabled_prices) if enabled_prices else 0

    product, created = Product.objects.update_or_create(
        printify_product_id=printify_product_id,
        defaults={
            'brand': brand,
            'blueprint_id': blueprint_id,
            'print_provider_id': print_provider_id,
            'title': title,
            'slug': slug,
            'description': description,
            'tags': tags,
            'base_retail_price_cents': base_price_cents,
            'is_published': is_visible,
            'last_synced_at': timezone.now(),
        },
    )

    # Brand drift safety net: if a product changes shop ownership.
    if not created and product.brand_id != brand.id:
        logger.warning(
            'Product %s changed brand from %s to %s; updating.',
            printify_product_id, product.brand_id, brand.id,
        )
        product.brand = brand
        product.save(update_fields=['brand'])

    # ---- Variants -----------------------------------------------------------
    seen_variant_ids: set[int] = set()
    for raw_variant in printify_variants:
        vid = int(raw_variant['id'])
        seen_variant_ids.add(vid)
        _upsert_variant(product, raw_variant, option_value_map, stats)

    # Soft-delete variants no longer present in Printify (preserves OrderItem FKs).
    disabled = (
        Variant.objects
        .filter(product=product, is_enabled=True)
        .exclude(printify_variant_id__in=seen_variant_ids)
        .update(is_enabled=False)
    )
    stats['variants_disabled'] += disabled

    # ---- Images (replace wholesale) -----------------------------------------
    _replace_images(product, data.get('images') or [], stats)

    return product, ('created' if created else 'updated')


def _upsert_variant(
    product: Product,
    data: dict,
    option_value_map: dict[int, tuple[str, str]],
    stats: dict,
) -> None:
    printify_variant_id = int(data['id'])
    stats['variants_seen'] += 1

    # Resolve size and color from the option-value map.
    size = ''
    color = ''
    for opt_id in data.get('options') or []:
        kind, value = option_value_map.get(int(opt_id), ('', ''))
        if kind == 'size' and not size:
            size = value
        elif kind == 'color' and not color:
            color = value

    _, created = Variant.objects.update_or_create(
        product=product,
        printify_variant_id=printify_variant_id,
        defaults={
            'sku': data.get('sku') or '',
            'title': data.get('title') or f'{size} / {color}'.strip(' /'),
            'size': size,
            'color': color,
            'price_cents': int(data.get('price', 0)),
            'cost_cents': int(data.get('cost', 0)),
            'is_available': bool(data.get('is_available', True)),
            'is_enabled': bool(data.get('is_enabled', True)),
        },
    )
    if created:
        stats['variants_created'] += 1
    else:
        stats['variants_updated'] += 1


def _replace_images(product: Product, raw_images: Iterable[dict], stats: dict) -> None:
    # Drop + bulk_create. ProductImage has no inbound FKs, so this is safe.
    product.images.all().delete()

    rows = []
    for idx, img in enumerate(raw_images):
        url = img.get('src')
        if not url:
            continue
        rows.append(ProductImage(
            product=product,
            url=url,
            is_default=bool(img.get('is_default', False)),
            position=idx,
            variant_ids=[int(v) for v in (img.get('variant_ids') or []) if v is not None],
        ))

    if rows:
        ProductImage.objects.bulk_create(rows)
        stats['images_replaced'] += len(rows)

    # If Printify didn't flag any image as default, promote the first by position.
    if not product.images.filter(is_default=True).exists():
        first = product.images.order_by('position').first()
        if first:
            first.is_default = True
            first.save(update_fields=['is_default'])


def _unique_slug_for_brand(brand: Brand, title: str, printify_product_id: str) -> str:
    """
    Generate a slug unique within the brand. Stable across re-syncs because
    the caller only invokes this on create (existing products keep their slug).
    """
    base = slugify(title)[:280] or 'product'
    if not Product.objects.filter(brand=brand, slug=base).exists():
        return base
    suffix = (printify_product_id or '')[-6:].lower()
    candidate = f'{base}-{suffix}' if suffix else f'{base}-1'
    n = 2
    while Product.objects.filter(brand=brand, slug=candidate).exists():
        candidate = f'{base}-{suffix}-{n}' if suffix else f'{base}-{n}'
        n += 1
    return candidate


# =============================================================================
# Helpers for callers that want a human-readable summary
# =============================================================================

def format_stats_summary(stats: dict) -> str:
    """
    Single-line summary string suitable for admin messages or scheduler logs.
    Mirrors the management command's end-of-run line.
    """
    return (
        f'{stats["products_seen"]} products seen, '
        f'{stats["products_created"]} created, '
        f'{stats["products_updated"]} updated, '
        f'{stats["products_failed"]} failed; '
        f'{stats["variants_created"]} variants created, '
        f'{stats["variants_disabled"]} variants soft-disabled.'
    )
