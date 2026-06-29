"""
sync_printify_products — pull a brand's Printify catalog into the local DB.

Usage:
    python manage.py sync_printify_products --brand=chesco.io
    python manage.py sync_printify_products --brand=chesco.io --dry-run
    python manage.py sync_printify_products --brand=chesco.io --limit-pages=1

This command is a thin wrapper around `catalog.services.sync_brand_catalog`,
which contains all the actual sync logic. The same logic is reused by:
  - The Django admin "Sync Now" action on a Brand (Sprint 3)
  - The Printify product:publish:started webhook handler (Sprint 4,
    via sync_one_product for single-product updates)

Heroku Scheduler runs this hourly. See sprintplans/eg_apparel_sprint_plan.md.

Behavior:
- Iterates all pages of products from Printify (limit=50 per page).
- Per-product upserts are transactional; one bad product does not halt the run.
- Variants no longer present in Printify are soft-disabled (is_enabled=False)
  rather than deleted, preserving FK integrity for historical OrderItems.
- Images are replaced wholesale on each sync.
- Idempotent: re-running yields the same result.
"""

from django.core.management.base import BaseCommand, CommandError

from brands.models import Brand
from catalog.printify_client import PrintifyError
from catalog.services import format_stats_summary, sync_brand_catalog


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

    def handle(self, *args, **options):
        domain = options['brand']
        dry_run = options['dry_run']
        limit_pages = options['limit_pages']

        try:
            brand = Brand.objects.get(domain=domain)
        except Brand.DoesNotExist:
            raise CommandError(f'Brand with domain={domain!r} does not exist.')

        self.stdout.write(self.style.NOTICE(
            f'Syncing Printify shop {brand.printify_shop_id} -> brand={brand.name}'
            f'{" (DRY RUN)" if dry_run else ""}'
        ))

        try:
            stats = sync_brand_catalog(brand, dry_run=dry_run, limit_pages=limit_pages)
        except ValueError as e:
            raise CommandError(str(e))
        except PrintifyError as e:
            raise CommandError(f'Printify API failure: {e}')

        # Detailed per-counter breakdown.
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Sync complete.'))
        for key, val in stats.items():
            self.stdout.write(f'  {key:.<25} {val}')

        # Single-line summary at the very end. The Django admin "Sync Now" action
        # uses sync_brand_catalog directly (not this command) and reads the stats
        # dict, but this line is also handy as a grep target in scheduler logs.
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'SUMMARY: {format_stats_summary(stats)}'
        ))
