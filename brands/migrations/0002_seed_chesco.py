"""
Seed the Chester County Apparel Co. brand record.

Run automatically by `manage.py migrate`. Idempotent: uses
update_or_create against the chesco.io domain so re-running the
migration after editing the brand in admin won't clobber your changes —
except for fields the migration explicitly sets (which match the
intended seed values).

If you need to edit the brand after seeding, prefer the Django admin
rather than amending this migration; this file is the canonical
"birth certificate" of the brand and should stay stable.
"""

from django.db import migrations


SEED_DOMAIN = 'chesco.io'

SEED_DEFAULTS = {
    'name': 'Chester County Apparel Co.',
    'tagline': 'Made for the 610.',
    'description': 'Apparel for people who live, work, and play in Chester County.',
    'primary_color': '#1a4d2e',   # deep pine green
    'accent_color': '#f4a261',    # warm field-grass amber
    'font_family': 'Inter',
    'from_email': 'hello@chesco.io',
    'support_email': 'hello@chesco.io',
    'is_active': True,
}


def seed_chesco(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    Brand.objects.update_or_create(
        domain=SEED_DOMAIN,
        defaults=SEED_DEFAULTS,
    )


def unseed_chesco(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    Brand.objects.filter(domain=SEED_DOMAIN).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_chesco, reverse_code=unseed_chesco),
    ]
