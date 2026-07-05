"""
Point the Chester County Apparel Co. brand's transactional email addresses at
dedicated mailboxes.

  from_email    -> noreply@chesco.io  (FROM for ALL outbound transactional mail:
                                       contact-form notification, order
                                       confirmation, shipped notice, and the
                                       internal order-failure alert)
  support_email -> admin@chesco.io    (TO for the contact-form notification and
                                       the internal order-failure alert; NOTE
                                       this is ALSO the customer-facing support
                                       address rendered in the footer mailto and
                                       referenced in the order emails)

Split so the sender (noreply@) and the recipient (admin@) differ: Hostinger
SMTP is unreliable when the From and To are the same mailbox.

Done as a data migration (mirroring 0003_recolor_chesco) rather than an admin
edit so a fresh install / disaster-recovery restore lands on the correct
routing instead of the seed's hello@chesco.io. Idempotent and defensive:
.update() on a missing row is a no-op.

OPERATIONAL (not handled here): sending also requires the noreply@chesco.io
mailbox to exist at Hostinger with EMAIL_HOST_USER / EMAIL_HOST_PASSWORD set in
Heroku config (the From should match the authenticated mailbox), and the
admin@chesco.io mailbox to exist to receive. This migration only sets the two
addresses on the Brand row; it does not configure SMTP.
"""

from django.db import migrations


SEED_DOMAIN = 'chesco.io'

NEW_EMAILS = {'from_email': 'noreply@chesco.io', 'support_email': 'admin@chesco.io'}
OLD_EMAILS = {'from_email': 'hello@chesco.io', 'support_email': 'hello@chesco.io'}


def apply_emails(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    Brand.objects.filter(domain=SEED_DOMAIN).update(**NEW_EMAILS)


def revert_emails(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    Brand.objects.filter(domain=SEED_DOMAIN).update(**OLD_EMAILS)


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0003_recolor_chesco'),
    ]

    operations = [
        migrations.RunPython(apply_emails, reverse_code=revert_emails),
    ]
