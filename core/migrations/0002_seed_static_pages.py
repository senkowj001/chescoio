"""
Seed DRAFT StaticPage content for the chesco.io brand (Sprint 5).

IMPORTANT — legal copy is UNPUBLISHED pending John's sign-off:
  - about, size-guide  -> is_published=True   (safe marketing copy, live)
  - privacy, terms,
    returns, shipping   -> is_published=False  (DRAFT — 404s for the public,
                                                previewable by staff only)
Every page is seeded needs_review=True as an admin checklist flag. The sprint
plan is explicit that returns/privacy must not ship without approval, so the
legal pages go in unpublished; John reviews the copy in admin, edits as needed,
unchecks needs_review, and flips is_published when he's satisfied.

Idempotency: this uses get_or_create (NOT update_or_create). Re-running migrate
after John has edited a page in admin will NOT clobber his edits — if a
(brand, slug) row already exists it's left untouched. That's the correct
trade-off for seed *content* (as opposed to the brand record, whose operational
fields we do want to keep authoritative).

Defensive: if the brand row doesn't exist yet (edge DB state) the seed is a
no-op rather than an error.
"""

from django.db import migrations


SEED_DOMAIN = 'chesco.io'

# Each entry becomes a StaticPage via get_or_create(brand, slug, defaults=...).
# Content is Markdown; the page <h1> is the template's job, so headings inside
# the body start at ## (h2). Keep each paragraph on a single line — the
# markdownify filter enables nl2br, so hard-wrapping mid-paragraph would inject
# <br> tags.
PAGES = [
    {
        'slug': 'about',
        'title': 'About Chester County Apparel Co.',
        'is_published': True,
        'sort_order': 10,
        'meta_description': (
            'Apparel made for the 610 — designed for the people who live, '
            'work, and play in Chester County, Pennsylvania.'
        ),
        'content': """\
## Made for the 610.

Chester County Apparel Co. makes clothing for the people who call this corner of Pennsylvania home. From the borough sidewalks to the back roads, from Friday-night games to Saturday-morning farm markets — this is apparel with a sense of place.

## What we're about

We started with a simple idea: local pride deserves better than a bargain-bin souvenir tee. Every design is drawn with Chester County in mind, printed on quality blanks, and made to be worn until it's your favorite thing in the drawer.

## How it's made

Our products are printed on demand, one order at a time. That means less waste, no overstock landfills, and a fresh print made specifically for you when you order. It also means we can offer a wider range of designs and sizes than we ever could holding inventory.

## Get in touch

Questions, ideas, or a design you'd love to see? We'd genuinely like to hear it. Reach us any time at hello@chesco.io.
""",
    },
    {
        'slug': 'size-guide',
        'title': 'Size Guide',
        'is_published': True,
        'sort_order': 20,
        'meta_description': (
            'Find your fit. General sizing and how-to-measure guidance for '
            'Chester County Apparel Co. tees and hoodies.'
        ),
        'content': """\
## Finding your fit

Our products are printed on quality blanks from established garment makers. Because we print on demand across a few different blank styles, the measurements below are a general guide — individual products may list their own specific measurements on the product page, so check there first when it's available.

If you're between sizes or prefer a roomier fit, size up.

## Unisex t-shirts

Measurements are approximate, in inches, laid flat.

| Size | Chest (in) | Body length (in) |
| --- | --- | --- |
| S | 34-37 | 28 |
| M | 38-41 | 29 |
| L | 42-45 | 30 |
| XL | 46-49 | 31 |
| 2XL | 50-53 | 32 |
| 3XL | 54-57 | 33 |

## Unisex hoodies & crewnecks

| Size | Chest (in) | Body length (in) |
| --- | --- | --- |
| S | 36-38 | 27 |
| M | 40-42 | 28 |
| L | 44-46 | 29 |
| XL | 48-50 | 30 |
| 2XL | 52-54 | 31 |
| 3XL | 56-58 | 32 |

## How to measure

The most reliable guide is a shirt you already own and love. Lay it flat and measure across the chest, one inch below the armhole, then double it — that's the chest measurement to compare against the chart. For length, measure from the highest point of the shoulder straight down to the hem.

Still not sure? Email hello@chesco.io and we'll help you dial it in.
""",
    },
    {
        'slug': 'shipping',
        'title': 'Shipping Policy',
        'is_published': False,
        'sort_order': 30,
        'meta_description': (
            'Shipping information for Chester County Apparel Co.: US '
            'delivery, production and transit times, and tracking.'
        ),
        'content': """\
## Where we ship

We currently ship within the United States only. We hope to expand beyond the US in the future — if international shipping matters to you, let us know at hello@chesco.io.

## Production and delivery time

Every order is printed on demand, made just for you. Here's what to expect:

- **Production:** typically 2-7 business days to print and prepare your order.
- **Transit:** typically 3-5 business days once shipped.
- **Total:** most orders arrive within roughly 5-10 business days.

These are estimates, not guarantees. Production and carrier times can run longer during holidays, sales, or periods of high demand.

## Shipping costs

Shipping is calculated at checkout based on your order and destination. The exact amount is shown before you pay — there are no surprise fees added afterward.

## Tracking

Once your order ships, we'll email you a tracking link. You can also look up your order status any time using your order number and email on our order-lookup page.

## Address accuracy

Please double-check your shipping address at checkout. We're not able to reroute a package once it's in production, and we can't cover the cost of reshipping an order returned to us because of an incorrect or incomplete address.

## Lost, delayed, or damaged in transit

If your tracking shows a problem, a package is significantly delayed, or your order arrives damaged, email hello@chesco.io and we'll make it right. See our Returns & Refunds policy for details on damaged or defective items.
""",
    },
    {
        'slug': 'returns',
        'title': 'Returns & Refunds',
        'is_published': False,
        'sort_order': 40,
        'meta_description': (
            'Returns and refunds at Chester County Apparel Co. — how we '
            'handle defective, damaged, or incorrect print-on-demand orders.'
        ),
        'content': """\
## The short version

Because every item is printed on demand and made specifically for your order, we are not able to accept returns or exchanges for buyer's remorse or for ordering the wrong size. All sales are final **except** where an item arrives defective, damaged, or not as ordered — those we will always make right.

Please use our Size Guide before ordering; we're glad to help you choose a size at hello@chesco.io.

## Defective, damaged, or wrong item

If your order arrives with a printing defect, damage from shipping, or is not the item you ordered, contact us within **14 days of delivery** and we'll arrange a free replacement or a refund.

To help us resolve it quickly, please include:

- Your order number
- The email used to place the order
- A photo clearly showing the defect, damage, or error

Email everything to hello@chesco.io.

## Refunds

Approved refunds are issued to your original payment method. Once processed, it typically takes your bank or card issuer several business days to post the credit — that timing is on their end, not ours.

## Order cancellations

Because production can begin quickly, we can't guarantee a change or cancellation after an order is placed. If you need to change or cancel, email hello@chesco.io as soon as possible and we'll do our best to help before the order enters production.

## Questions

Anything at all — reach us at hello@chesco.io and a real person will get back to you.
""",
    },
    {
        'slug': 'privacy',
        'title': 'Privacy Policy',
        'is_published': False,
        'sort_order': 50,
        'meta_description': (
            'How Chester County Apparel Co. collects, uses, and protects '
            'your information.'
        ),
        'content': """\
## Overview

This policy explains what information Chester County Apparel Co. ("we," "us") collects when you visit chesco.io or place an order, how we use it, and the choices you have. We collect only what we need to run the shop and fulfill your orders.

## Information we collect

- **Order and contact information** you provide at checkout: your name, email address, shipping address, and phone number (if given).
- **Messages** you send us through our contact form or by email.
- **Email sign-ups**, if you choose to join our list for new releases.
- **Basic usage data** collected automatically to keep the site working and understand what's popular (see Analytics below).

We do **not** see or store your full payment-card details. Payments are processed by our payment provider (see below).

## Payments

Card payments are handled by **Stripe**. Your card information is submitted directly to Stripe and is subject to Stripe's privacy policy. We receive confirmation of payment and limited transaction details, but never your full card number.

## Order fulfillment

Our products are produced and shipped by our print-on-demand fulfillment partner. To fulfill your order, we share the information needed to make and ship it — your name, shipping address, and order contents — with that partner. They use it only to produce and deliver your order.

## Analytics

We use privacy-friendly analytics to understand overall site traffic. We may also use the **Meta (Facebook) Pixel** to measure the effectiveness of advertising and to understand which visits lead to orders; this involves cookies and may allow Meta to associate your activity with a Meta account, subject to Meta's own policies. Where required, we present a cookie or consent choice.

## Cookies

We use cookies and similar technologies to keep your shopping cart working, secure the site, and (where applicable) support the analytics and advertising measurement described above. You can control cookies through your browser settings; disabling some cookies may affect how the site works.

## How we use your information

We use your information to process and deliver orders, provide customer support, send order and shipping notifications, send marketing emails if you've opted in, prevent fraud and abuse, and comply with our legal obligations.

## Your choices and rights

You can unsubscribe from marketing emails at any time using the link in those emails. You may request access to, correction of, or deletion of your personal information by emailing hello@chesco.io, and we'll respond consistent with applicable law. Depending on where you live, you may have additional rights over your personal information.

## Data retention

We keep order records for as long as needed to provide the service, meet legal, tax, and accounting requirements, and resolve disputes.

## Children

Our store is intended for adults and is not directed to children under 13, and we do not knowingly collect personal information from children under 13.

## Changes to this policy

We may update this policy from time to time. Material changes will be reflected by updating the effective date on this page.

## Contact

Questions about privacy? Email hello@chesco.io.
""",
    },
    {
        'slug': 'terms',
        'title': 'Terms of Service',
        'is_published': False,
        'sort_order': 60,
        'meta_description': (
            'The terms and conditions for using chesco.io and purchasing '
            'from Chester County Apparel Co.'
        ),
        'content': """\
## Agreement to terms

By accessing chesco.io or placing an order, you agree to these Terms of Service. If you don't agree, please don't use the site. We may update these terms from time to time; the version in effect is the one posted here.

## Eligibility

You must be able to form a binding contract to purchase from us. If you're under the age of majority in your state, you may use the site only with the involvement of a parent or guardian.

## Products and pricing

We work hard to describe and picture our products accurately, but we don't warrant that product descriptions, colors, or other content are error-free, and screens vary in how they display color. Prices are shown in US dollars and may change at any time before you place an order. We reserve the right to correct errors and to limit or cancel quantities.

## Orders and payment

Submitting an order is an offer to buy, which we may accept or decline. Payment is processed by Stripe at checkout. If we can't fulfill an order — for example, a pricing error or a product issue — we may cancel it and refund any amount charged.

## Shipping and returns

Shipping is governed by our Shipping Policy and returns by our Returns & Refunds policy, both of which are part of these terms.

## Intellectual property

All designs, artwork, logos, and site content are owned by Chester County Apparel Co. or our licensors and are protected by law. You may not reproduce, resell, or create derivative products from our designs without our written permission.

## Acceptable use

You agree not to misuse the site — including attempting to disrupt it, access it without authorization, scrape it, or use it for any unlawful purpose.

## Disclaimers

The site and products are provided on an "as is" and "as available" basis without warranties of any kind, to the fullest extent permitted by law, except for any warranties that cannot legally be excluded.

## Limitation of liability

To the fullest extent permitted by law, Chester County Apparel Co. will not be liable for any indirect, incidental, special, or consequential damages arising from your use of the site or products. Nothing in these terms limits liability that cannot legally be limited.

## Governing law

These terms are governed by the laws of the Commonwealth of Pennsylvania, without regard to its conflict-of-laws rules. Any dispute will be brought in the state or federal courts located in Pennsylvania, and you consent to their jurisdiction.

## Contact

Questions about these terms? Email hello@chesco.io.
""",
    },
]


def seed_static_pages(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    StaticPage = apps.get_model('core', 'StaticPage')

    try:
        brand = Brand.objects.get(domain=SEED_DOMAIN)
    except Brand.DoesNotExist:
        # Edge DB state (brand not seeded). Nothing to attach pages to; skip
        # cleanly rather than erroring out the migration.
        return

    for page in PAGES:
        StaticPage.objects.get_or_create(
            brand=brand,
            slug=page['slug'],
            defaults={
                'title': page['title'],
                'content': page['content'],
                'meta_description': page['meta_description'],
                'is_published': page['is_published'],
                'needs_review': True,
                'sort_order': page['sort_order'],
            },
        )


def unseed_static_pages(apps, schema_editor):
    Brand = apps.get_model('brands', 'Brand')
    StaticPage = apps.get_model('core', 'StaticPage')

    try:
        brand = Brand.objects.get(domain=SEED_DOMAIN)
    except Brand.DoesNotExist:
        return

    slugs = [p['slug'] for p in PAGES]
    StaticPage.objects.filter(brand=brand, slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('brands', '0002_seed_chesco'),
    ]

    operations = [
        migrations.RunPython(seed_static_pages, reverse_code=unseed_static_pages),
    ]
