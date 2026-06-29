"""
sync_printify_products — pull a brand's Printify catalog into the local DB.

Usage:
    python manage.py sync_printify_products --brand=chesco.io
    python manage.py sync_printify_products --brand=chesco.io --dry-run

Behavior:
- Iterates all pages from Printify list_products (limit=50).
- For each product, runs upsert (Product + Variants + Images) inside a single
  transaction. A failure on any one product aborts that product's transaction
  but does not stop the run for other products.
- Variants that exist locally but no longer appear in Printify for the product
  are marked is_enabled=False (soft delete) so historical OrderItem FKs stay
  valid.
- Images are replaced wholesale on each sync (Printify image URLs are stable
  per upload, so a re-sync after no Printify changes is a no-op delete/insert
  of the same URLs — acceptable for v1).
- Idempotent: safe to run repeatedly. update_or_create on printify_product_id /
  (product, printify_variant_id) is the natural key.

Heroku Scheduler runs this nightly at 03:00 UTC. See sprintplans/eg_apparel_sprint_plan.md.
"""

import logging
from collections.abc import Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from brands.models import Brand
from catalog.models import Product, ProductImage, Variant
from catalog.printify_client import PrintifyClient, PrintifyError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync Printify products into the local catalog for the given brand."

    def add_arguments(self, parser):
        parser.add_argument(
            '--brand',
            required=True,
            help='Brand domain (e.g. chesco.io). Brand must exist and have printify_shop_id set.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Fetch from Printify and report counts; do not write to DB.',
        )
        parser.add_argument(
            '--limit-pages',
            type=int,
            default=None,
            help='For debugging: stop after this many pages of products.',
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        domain = options['brand']
        dry_run = options['dry_run']
        limit_pages = options['limit_pages']

        try:
            brand = Brand.objects.get(domain=domain)
        except Brand.DoesNotExist:
            raise CommandError(f'Brand with domain={domain!r} does not exist.')

        if not brand.printify_shop_id:
            raise CommandError(
                f'Brand {brand.name} ({brand.domain}) has no printify_shop_id. '
                f'Set it via Django admin before running sync.'
            )

        self.stdout.write(self.style.NOTICE(
            f'Syncing Printify shop {brand.printify_shop_id} -> brand={brand.name} '
            f'{"(DRY RUN)" if dry_run else ""}'
        ))

        try:
            client = PrintifyClient()
        except PrintifyError as e:
            raise CommandError(str(e))

        # Counters for end-of-run summary
        stats = {
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

        page = 1
        while True:
            try:
                resp = client.list_products(brand.printify_shop_id, page=page, limit=50)
            except PrintifyError as e:
                raise CommandError(f'Printify list_products page {page} failed: {e}')

            products = resp.get('data') or []
            stats['pages'] += 1
            self.stdout.write(f'  page {page}: {len(products)} products')

            for printify_product in products:
                stats['products_seen'] += 1
                pid = printify_product.get('id', '?')
                try:
                    if dry_run:
                        # Just count; no DB writes.
                        continue
                    result = self._sync_one_product(brand, printify_product, stats)
                    if result == 'created':
                        stats['products_created'] += 1
                    elif result == 'updated':
                        stats['products_updated'] += 1
                except Exception as e:  # noqa: BLE001 — we want to log and continue
                    stats['products_failed'] += 1
                    logger.exception(
                        'Failed to sync Printify product %s for brand %s: %s',
                        pid, brand.domain, e,
                    )
                    self.stderr.write(self.style.ERROR(
                        f'  ✗ product {pid}: {e}'
                    ))

            if not resp.get('next_page_url'):
                break
            page += 1
            if limit_pages and page > limit_pages:
                self.stdout.write(self.style.WARNING(
                    f'Stopping at --limit-pages={limit_pages}'
                ))
                break

        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Sync complete.'))
        for key, val in stats.items():
            self.stdout.write(f'  {key:.<25} {val}')

    # ------------------------------------------------------------------
    # Per-product upsert (transactional)
    # ------------------------------------------------------------------

    @transaction.atomic
    def _sync_one_product(self, brand: Brand, data: dict, stats: dict) -> str:
        """
        Upsert one product + its variants + its images. All-or-nothing per product.
        Returns 'created' or 'updated'.
        """
        printify_product_id = str(data['id'])
        title = data.get('title', '').strip() or f'Untitled {printify_product_id}'
        description = data.get('description') or ''
        tags = data.get('tags') or []
        blueprint_id = data.get('blueprint_id') or 0
        print_provider_id = data.get('print_provider_id') or 0
        is_visible = bool(data.get('visible', True))

        # ---- Build option map: option_id (int) -> (kind, value_str) ----------
        # Printify product.options example:
        #   [
        #     {"name": "Size",  "type": "size",  "values": [{"id": 14, "title": "S"}, ...]},
        #     {"name": "Color", "type": "color", "values": [{"id": 1, "title": "Black"}, ...]}
        #   ]
        # Variant.options is then a list of value-ids, e.g. [14, 1] = "S / Black".
        option_value_map: dict[int, tuple[str, str]] = {}
        for opt in data.get('options') or []:
            kind = (opt.get('type') or opt.get('name') or '').lower()
            for v in opt.get('values') or []:
                vid = v.get('id')
                if vid is None:
                    continue
                option_value_map[int(vid)] = (kind, str(v.get('title', '')))

        # ---- Slug — generate once on create; keep stable on subsequent syncs --
        existing = Product.objects.filter(printify_product_id=printify_product_id).first()
        if existing:
            slug = existing.slug
        else:
            slug = self._unique_slug_for_brand(brand, title, printify_product_id)

        # ---- Compute base_retail_price_cents from cheapest enabled variant ----
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

        # If we just resurrected a product whose brand changed, log it.
        if not created and product.brand_id != brand.id:
            logger.warning(
                'Product %s changed brand from %s to %s; updating.',
                printify_product_id, product.brand_id, brand.id,
            )
            product.brand = brand
            product.save(update_fields=['brand'])

        # ---- Sync variants ---------------------------------------------------
        seen_variant_ids: set[int] = set()
        for raw_variant in printify_variants:
            vid = int(raw_variant['id'])
            seen_variant_ids.add(vid)
            self._upsert_variant(product, raw_variant, option_value_map, stats)

        # Soft-delete variants no longer present (preserves order history FKs).
        disabled = (
            Variant.objects
            .filter(product=product, is_enabled=True)
            .exclude(printify_variant_id__in=seen_variant_ids)
            .update(is_enabled=False)
        )
        stats['variants_disabled'] += disabled

        # ---- Replace images wholesale ---------------------------------------
        # Printify image URLs change when designs change, and there's no stable
        # local-only data on ProductImage. Easier to drop & re-insert per sync.
        self._replace_images(product, data.get('images') or [], stats)

        return 'created' if created else 'updated'

    # ------------------------------------------------------------------

    def _upsert_variant(
        self,
        product: Product,
        data: dict,
        option_value_map: dict[int, tuple[str, str]],
        stats: dict,
    ) -> None:
        printify_variant_id = int(data['id'])
        stats['variants_seen'] += 1

        # Resolve size / color from the option map
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

    # ------------------------------------------------------------------

    def _replace_images(self, product: Product, raw_images: Iterable[dict], stats: dict) -> None:
        # Delete existing, re-insert from Printify response.
        product.images.all().delete()

        rows = []
        for idx, img in enumerate(raw_images):
            url = img.get('src')
            if not url:
                continue
            # Printify "position" is a label ("front", "back", "side") not an int.
            # Use enumeration order for the local position; mark Printify default.
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

    # ------------------------------------------------------------------

    def _unique_slug_for_brand(self, brand: Brand, title: str, printify_product_id: str) -> str:
        """
        Return a slug unique within the brand. If slugify(title) collides with
        an existing brand product (different printify_product_id), append a
        short suffix derived from the printify_product_id for stability.
        """
        base = slugify(title)[:280] or 'product'
        if not Product.objects.filter(brand=brand, slug=base).exists():
            return base
        # Use last 6 chars of the printify id as a deterministic disambiguator.
        suffix = (printify_product_id or '')[-6:].lower()
        candidate = f'{base}-{suffix}' if suffix else f'{base}-1'
        # In the unlikely event the suffixed slug also collides, increment.
        n = 2
        while Product.objects.filter(brand=brand, slug=candidate).exists():
            candidate = f'{base}-{suffix}-{n}' if suffix else f'{base}-{n}'
            n += 1
        return candidate
