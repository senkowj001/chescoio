"""
Recolor the Chester County Apparel Co. brand (design revision).

Splits the two brand-color roles that were previously both driving the same
green:
  - primary_color -> #000052 (deep navy): the wordmark / heading color
  - accent_color  -> #0a6ed3 (blue):      the button / call-to-action color

Done as a data migration rather than an edit to 0002_seed_chesco (which stays
the brand's stable "birth certificate") so it updates the existing row on
`migrate` and, on a fresh install, runs immediately after the seed to land on
the new colors. Idempotent and defensive: `.update()` on a missing row is a
no-op, so this can't fail on an edge database.

Templates read these values as the CSS variables --color-brand-primary /
--color-brand-accent (see base.html); headings and the wordmark use primary,
buttons use accent.
"""

from django.db import migrations


SEED_DOMAIN = 'chesco.io'

NEW_COLORS = {'primary_color': '#000052', 'accent_color': '#0a6ed3'}
OLD_COLORS = {'primary_color': '#1a4d2e', 'accent_color': '#f4a261'}


def apply_colors(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    Brand.objects.filter(domain=SEED_DOMAIN).update(**NEW_COLORS)


def revert_colors(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    Brand.objects.filter(domain=SEED_DOMAIN).update(**OLD_COLORS)


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0002_seed_chesco'),
    ]

    operations = [
        migrations.RunPython(apply_colors, reverse_code=revert_colors),
    ]
