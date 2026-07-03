"""
clear_old_carts — delete carts older than CART_EXPIRY_DAYS.

Usage:
    python manage.py clear_old_carts
    python manage.py clear_old_carts --dry-run
    python manage.py clear_old_carts --days=14

Rationale:
    Carts are session-keyed and abandoned frequently. Without periodic
    cleanup, the orders_cart table grows unbounded. More importantly, the
    (brand, session_key) unique constraint would block a returning-customer
    session if the session_key ever recycles (rare but possible across years
    of runtime).

    Wire up as a daily Heroku Scheduler job at Sprint 5 launch time:
        python manage.py clear_old_carts

    Idempotent, safe to re-run. Deletes Carts only (CartItems cascade); does
    not touch Orders or OrderItems, which are snapshotted at checkout and
    live independently of the cart they came from.

Reads CART_EXPIRY_DAYS from settings (default 7 if absent). --days overrides
for manual runs, e.g. before a big cleanup or when debugging.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from orders.models import Cart


class Command(BaseCommand):
    help = "Delete carts older than CART_EXPIRY_DAYS (default 7)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be deleted without deleting.',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Override CART_EXPIRY_DAYS from settings.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        days = options['days'] if options['days'] is not None else getattr(
            settings, 'CART_EXPIRY_DAYS', 7,
        )
        if days < 1:
            self.stderr.write(self.style.ERROR(
                f'--days must be >= 1 (got {days}). Refusing to run.'
            ))
            return

        cutoff = timezone.now() - timedelta(days=days)

        # Annotate with item counts up front so we can report both totals
        # without a second query per cart. queryset is deliberately unforced
        # (no list()) so the delete below hits the DB, not the Python objects.
        expired = Cart.objects.filter(updated_at__lt=cutoff).annotate(
            item_count=Count('items'),
        )

        cart_count = expired.count()
        if cart_count == 0:
            self.stdout.write(f'No carts older than {days} days. Nothing to do.')
            return

        # Sum item counts across expired carts. Small enough that materializing
        # is cheap; large-catalog concerns would justify aggregate() instead.
        expired_carts = list(expired.values('pk', 'brand__domain', 'session_key', 'item_count', 'updated_at'))
        item_count = sum(c['item_count'] for c in expired_carts)

        header = (
            f'{"DRY RUN: " if dry_run else ""}'
            f'{cart_count} cart(s) with {item_count} item(s) '
            f'older than {days} days (updated_at < {cutoff:%Y-%m-%d %H:%M UTC}).'
        )
        self.stdout.write(header)

        # Show first ~10 for a sanity check; suppress the rest to keep the
        # scheduler log tidy on a large run.
        for c in expired_carts[:10]:
            self.stdout.write(
                f'  cart_id={c["pk"]} brand={c["brand__domain"]} '
                f'session={c["session_key"][:12] + "..." if c["session_key"] else "(none)"} '
                f'items={c["item_count"]} '
                f'updated_at={c["updated_at"]:%Y-%m-%d}'
            )
        if len(expired_carts) > 10:
            self.stdout.write(f'  ... and {len(expired_carts) - 10} more')

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN: no rows deleted.'))
            return

        # Cascades to CartItems. Orders + OrderItems are unaffected — they
        # have no FK to Cart (line data is snapshotted at checkout).
        deleted_total, deleted_by_model = expired.delete()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {deleted_total} row(s) across {len(deleted_by_model)} model(s): '
            f'{dict(deleted_by_model)}'
        ))
