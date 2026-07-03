"""
register_printify_webhooks -- idempotently register/reconcile Printify
webhook subscriptions for a brand's shop.

Printify has no dashboard UI for webhook subscriptions; registration is
API-only via POST /v1/shops/{shop_id}/webhooks.json. This command:

  1. Lists existing webhooks for the brand's printify_shop_id
  2. Computes the desired set: the four order:* topics + three product:*
     topics handled in orders/views.py::printify_webhook, all pointing at
     https://{brand.domain}/webhooks/printify/, all using
     settings.PRINTIFY_WEBHOOK_SECRET
  3. Creates missing subscriptions, updates ones with a stale URL, leaves
     correct ones alone
  4. With --prune, deletes subscriptions that exist but aren't in the
     desired topic set (stray/duplicate subscriptions)

Same structural template as scripts/configure_stripe_dev.py: list current
state, compute diff, apply changes, print summary.

Usage:
    python manage.py register_printify_webhooks --brand=chesco.io
    python manage.py register_printify_webhooks --brand=chesco.io --dry-run
    python manage.py register_printify_webhooks --brand=chesco.io --prune

Run once per brand at Sprint 4 deployment time. Safe to re-run any time the
topic list or target URL changes -- that's the whole point of idempotency
here, since there's no dashboard to eyeball the current state.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from brands.models import Brand
from catalog.printify_client import PrintifyClient, PrintifyError

# Must match orders/views.py::PRINTIFY_HANDLED_EVENT_TYPES exactly -- these
# are the topics we actually have handlers for.
DESIRED_TOPICS = [
    'order:created',
    'order:sent-to-production',
    'order:shipment:created',
    'order:shipment:delivered',
    'product:publish:started',
    'product:publish:succeeded',
    'product:deleted',
]


class Command(BaseCommand):
    help = "Idempotently register/reconcile Printify webhook subscriptions for a brand's shop."

    def add_arguments(self, parser):
        parser.add_argument('--brand', required=True, help='Brand domain (e.g. chesco.io)')
        parser.add_argument('--dry-run', action='store_true', help='Show the plan without making changes')
        parser.add_argument(
            '--prune', action='store_true',
            help='Delete existing subscriptions that are not in the desired topic set',
        )

    def handle(self, *args, **options):
        domain = options['brand']
        dry_run = options['dry_run']
        prune = options['prune']

        try:
            brand = Brand.objects.get(domain=domain)
        except Brand.DoesNotExist:
            raise CommandError(f'Brand with domain={domain!r} does not exist.')

        if not brand.printify_shop_id:
            raise CommandError(f'Brand {brand.name} has no printify_shop_id set.')

        secret = getattr(settings, 'PRINTIFY_WEBHOOK_SECRET', '')
        if not secret:
            raise CommandError(
                'PRINTIFY_WEBHOOK_SECRET is not set. Generate one '
                "(python -c \"import secrets; print(secrets.token_urlsafe(32))\") "
                'and set it in .env / Heroku config before registering webhooks.'
            )

        target_url = f'https://{brand.domain}/webhooks/printify/'

        client = PrintifyClient()
        try:
            existing = client.list_webhooks(brand.printify_shop_id)
        except PrintifyError as e:
            raise CommandError(f'Could not list existing webhooks: {e}')

        # Be defensive about response shape -- Printify's other list endpoints
        # use a paginated envelope, but webhooks.json is documented as a flat
        # array. Handle both so a shape change doesn't crash the command.
        existing_list = existing if isinstance(existing, list) else (existing or {}).get('data', [])

        by_topic: dict[str, list] = {}
        for hook in existing_list:
            by_topic.setdefault(hook.get('topic'), []).append(hook)

        self.stdout.write(self.style.NOTICE(
            f'Reconciling Printify webhooks for {brand.name} (shop {brand.printify_shop_id})'
            f'{" (DRY RUN)" if dry_run else ""}'
        ))
        self.stdout.write(f'  Target URL: {target_url}')
        self.stdout.write('')

        created = updated = unchanged = pruned = 0

        for topic in DESIRED_TOPICS:
            hooks_for_topic = by_topic.pop(topic, [])

            if not hooks_for_topic:
                self.stdout.write(f'  [create] {topic}')
                if not dry_run:
                    try:
                        client.create_webhook(brand.printify_shop_id, topic, target_url, secret)
                    except PrintifyError as e:
                        self.stderr.write(self.style.ERROR(f'    failed: {e}'))
                        continue
                created += 1
                continue

            # Topic already has at least one subscription. Reconcile the
            # first one found; any additional ones for the same topic are
            # duplicates and get flagged for pruning below.
            primary, *extras = hooks_for_topic
            if primary.get('url') != target_url:
                self.stdout.write(f'  [update] {topic} (stale URL: {primary.get("url")})')
                if not dry_run:
                    try:
                        client.update_webhook(
                            brand.printify_shop_id, primary['id'], url=target_url, secret=secret,
                        )
                    except PrintifyError as e:
                        self.stderr.write(self.style.ERROR(f'    failed: {e}'))
                        continue
                updated += 1
            else:
                self.stdout.write(f'  [ok]     {topic}')
                unchanged += 1

            for extra in extras:
                note = ' (pruning)' if prune else ' (use --prune to remove)'
                self.stdout.write(f'  [dupe]   {topic} id={extra.get("id")}{note}')
                if prune and not dry_run:
                    try:
                        client.delete_webhook(brand.printify_shop_id, extra['id'])
                        pruned += 1
                    except PrintifyError as e:
                        self.stderr.write(self.style.ERROR(f'    failed to delete: {e}'))

        # Anything left in by_topic subscribes to a topic we don't want --
        # leftover from an earlier sprint, manual API tinkering, etc.
        for topic, hooks in by_topic.items():
            for hook in hooks:
                note = ' (pruning)' if prune else ' (use --prune to remove)'
                self.stdout.write(f'  [stray]  {topic} id={hook.get("id")}{note}')
                if prune and not dry_run:
                    try:
                        client.delete_webhook(brand.printify_shop_id, hook['id'])
                        pruned += 1
                    except PrintifyError as e:
                        self.stderr.write(self.style.ERROR(f'    failed to delete: {e}'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. created={created} updated={updated} unchanged={unchanged} pruned={pruned}'
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN: no changes were made.'))
