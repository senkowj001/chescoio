"""
Core content models (Sprint 5).

These back the brand-scoped marketing / legal surface:

  - StaticPage: markdown-backed CMS pages (privacy, terms, returns, shipping,
    about, size-guide, and any future one-off page). Editable in admin so John
    can revise copy without a redeploy — the whole point of storing content in
    the DB rather than in templates. Rendered through the `markdownify` filter
    (core/templatetags/core_extras.py). Content is authored by staff via admin,
    so it's a trusted source: same rendering trust model as the Printify
    product descriptions the catalog already renders with |safe.
  - ContactMessage: an audit record of every contact-form submission, so a
    dropped or spam-filtered notification email doesn't mean a lost message.
  - EmailSignup: the "drop your email for new releases" list. is_confirmed
    stays False for v1 (no double opt-in until 2.0); the field exists now so a
    future confirmation flow doesn't need a migration.

Everything is scoped to a Brand (multi-brand from day one): a second brand
front on the same backend gets its own pages, its own contact log, and its own
signup list with no code change.
"""

from django.db import models
from django.urls import reverse

from brands.models import Brand


class StaticPage(models.Model):
    """
    A markdown CMS page scoped to a Brand.

    The canonical v1 slugs (about, privacy, terms, returns, shipping,
    size-guide) resolve at clean top-level URLs via named routes in core.urls;
    get_absolute_url maps those slugs to their friendly URL and falls back to
    /p/<slug>/ for any ad-hoc page. Per-brand slug uniqueness lets a second
    brand ship its own /privacy/ without colliding.

    is_published gates public visibility: an unpublished page 404s for the
    public but is previewable by logged-in staff (see core.views.static_page).
    needs_review is admin-only metadata — a checklist flag so John can track
    which drafts he's signed off on. It does NOT affect rendering.
    """

    # Canonical slug -> named URL. Ad-hoc pages fall back to core:static_page.
    _SLUG_TO_URL_NAME = {
        'about': 'core:about',
        'privacy': 'core:privacy',
        'terms': 'core:terms',
        'returns': 'core:returns',
        'shipping': 'core:shipping',
        'size-guide': 'core:size_guide',
    }

    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name='static_pages',
    )
    slug = models.SlugField(
        max_length=100,
        help_text='URL slug. Canonical pages: about, privacy, terms, returns, '
                  'shipping, size-guide. Others resolve at /p/<slug>/.',
    )
    title = models.CharField(max_length=200)
    content = models.TextField(
        blank=True,
        help_text='Markdown. Rendered to HTML on the page. Authored by staff, '
                  'so raw HTML in the markdown is allowed (trusted source).',
    )
    meta_description = models.CharField(
        max_length=300,
        blank=True,
        help_text='Optional. Used for the <meta name="description"> / OpenGraph '
                  'description on this page. Falls back to the page title.',
    )

    is_published = models.BooleanField(
        default=True,
        help_text='Unpublished pages 404 for the public but are previewable by '
                  'logged-in staff.',
    )
    needs_review = models.BooleanField(
        default=True,
        help_text='Admin checklist flag: content is a draft awaiting sign-off. '
                  'Does not affect what visitors see — uncheck once approved.',
    )
    sort_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'title']
        unique_together = [('brand', 'slug')]

    def __str__(self):
        return f'{self.title} ({self.brand.domain})'

    def get_absolute_url(self):
        name = self._SLUG_TO_URL_NAME.get(self.slug)
        if name:
            return reverse(name)
        return reverse('core:static_page', kwargs={'slug': self.slug})


class EmailSignup(models.Model):
    """
    A newsletter / new-release email signup, scoped to a Brand.

    Deduped per (brand, email): a repeat signup from the same address is a
    no-op, not a duplicate row (enforced in the view via get_or_create). No
    double opt-in for v1 — is_confirmed stays False and is reserved for a 2.0
    confirmation flow.
    """

    SOURCE_FOOTER = 'footer'
    SOURCE_HOMEPAGE = 'homepage'
    SOURCE_POPUP = 'popup'
    SOURCE_OTHER = 'other'
    SOURCE_CHOICES = [
        (SOURCE_FOOTER, 'Footer'),
        (SOURCE_HOMEPAGE, 'Homepage'),
        (SOURCE_POPUP, 'Popup'),
        (SOURCE_OTHER, 'Other'),
    ]

    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name='email_signups',
    )
    email = models.EmailField()
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_FOOTER,
    )
    is_confirmed = models.BooleanField(
        default=False,
        help_text='Reserved for a future double opt-in flow (2.0). False for v1.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('brand', 'email')]

    def __str__(self):
        return f'{self.email} ({self.brand.domain})'


class ContactMessage(models.Model):
    """
    An audit record of a contact-form submission.

    The form also emails the brand's support_email, but that email can be
    dropped or spam-filtered; persisting the message here means it's never
    lost. is_handled is a simple triage flag toggled in admin.
    """

    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name='contact_messages',
    )
    name = models.CharField(max_length=120)
    email = models.EmailField()
    message = models.TextField()

    is_handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} <{self.email}> ({self.created_at:%Y-%m-%d})'
