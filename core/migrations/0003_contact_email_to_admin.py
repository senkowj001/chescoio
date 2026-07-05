"""
Repoint the contact email in StaticPage copy from hello@chesco.io to
admin@chesco.io.

hello@chesco.io was never a real mailbox; admin@chesco.io is the brand's
actual address (Brand.support_email was pointed at it in brands/0004). The
Sprint 5 seed (core/0002) hard-coded hello@ throughout the page bodies —
including the already-PUBLISHED about and size-guide pages — so this migration
rewrites the live copy, not just future installs.

Layered as a new migration rather than editing 0002 (the seed stays the stable
"birth certificate" per its own docstring) so it also fixes already-migrated
databases on `migrate`. Safe and idempotent: a plain string replace, so pages
John has already edited to admin@ in the admin (or that never contained hello@)
are left untouched.
"""

from django.db import migrations


SEED_DOMAIN = 'chesco.io'
OLD_EMAIL = 'hello@chesco.io'
NEW_EMAIL = 'admin@chesco.io'


def _swap_email(apps, old, new):
    Brand = apps.get_model('brands', 'Brand')
    StaticPage = apps.get_model('core', 'StaticPage')

    try:
        brand = Brand.objects.get(domain=SEED_DOMAIN)
    except Brand.DoesNotExist:
        # Edge DB state (brand not seeded). Nothing to rewrite; skip cleanly.
        return

    for page in StaticPage.objects.filter(brand=brand):
        changed = False
        if old in (page.content or ''):
            page.content = page.content.replace(old, new)
            changed = True
        if old in (page.meta_description or ''):
            page.meta_description = page.meta_description.replace(old, new)
            changed = True
        if changed:
            page.save(update_fields=['content', 'meta_description'])


def apply_swap(apps, schema_editor):
    _swap_email(apps, OLD_EMAIL, NEW_EMAIL)


def revert_swap(apps, schema_editor):
    _swap_email(apps, NEW_EMAIL, OLD_EMAIL)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_seed_static_pages'),
    ]

    operations = [
        migrations.RunPython(apply_swap, reverse_code=revert_swap),
    ]
