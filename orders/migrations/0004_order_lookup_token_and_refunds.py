# Generated for Sprint 5 — public order-lookup token + refund tracking on Order.
#
# lookup_token is UNIQUE, so it can't be added in a single step to a table that
# may already hold rows (every existing Order would share the empty-string
# default and violate the constraint). Standard three-step dance:
#   1. add the column with a blank, non-unique default
#   2. backfill a unique token onto every existing row (RunPython)
#   3. alter the column to unique + the generate_lookup_token callable default
#
# Hand-written to match the Sprint 3/4 convention (this session edits the
# Windows filesystem directly and can't run `manage.py makemigrations`). John
# should run `python manage.py makemigrations --check` after pulling to confirm
# the model state and this migration agree, then `migrate`.

import secrets

import orders.models
from django.db import migrations, models


def populate_lookup_tokens(apps, schema_editor):
    """Assign a unique lookup_token to every pre-existing Order."""
    Order = apps.get_model('orders', 'Order')
    seen = set()
    for order in Order.objects.filter(lookup_token='').iterator():
        token = secrets.token_urlsafe(24)
        while token in seen:
            token = secrets.token_urlsafe(24)
        seen.add(token)
        order.lookup_token = token
        order.save(update_fields=['lookup_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_order_email_dedupe_guards'),
    ]

    operations = [
        # 1. Add non-unique with a blank default so existing rows are valid.
        migrations.AddField(
            model_name='order',
            name='lookup_token',
            field=models.CharField(default='', editable=False, max_length=64),
        ),
        # 2. Backfill unique tokens onto existing rows.
        migrations.RunPython(populate_lookup_tokens, migrations.RunPython.noop),
        # 3. Promote to unique + the callable default used for all new orders.
        migrations.AlterField(
            model_name='order',
            name='lookup_token',
            field=models.CharField(
                default=orders.models.generate_lookup_token,
                editable=False,
                max_length=64,
                unique=True,
            ),
        ),
        # Refund tracking.
        migrations.AddField(
            model_name='order',
            name='refunded_cents',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='order',
            name='refunded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
