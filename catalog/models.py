"""
Catalog models — local cache of Printify products, scoped per-Brand.

Source of truth is Printify. The `sync_printify_products` management command
upserts these rows on a nightly schedule (Heroku Scheduler) and on-demand.

Design notes:
- Product, Variant, ProductImage are pure caches. No business logic mutates
  them outside the sync command. Admin registers them read-only.
- Product.slug is scoped per-brand (unique_together with brand) so two brands
  can ship identically-named designs without colliding. BrandMiddleware already
  scopes lookups, so per-brand uniqueness is sufficient.
- Variant.is_enabled is set False when a variant disappears from Printify
  (rather than deleting it) so historical OrderItems keep a valid FK target.
- Prices are stored in cents (integers) throughout — never in floats.
"""

from django.db import models
from django.urls import reverse

from brands.models import Brand


class Product(models.Model):
    """
    A Printify product, cached locally for fast catalog rendering.

    One Product per Printify product per brand. printify_product_id is globally
    unique because Printify mints them; we treat it as the natural key during
    sync (`update_or_create(printify_product_id=...)`).
    """

    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name='products',
    )

    # Printify identifiers
    printify_product_id = models.CharField(max_length=50, unique=True)
    blueprint_id = models.IntegerField(help_text='Printify blueprint, e.g. "Unisex Heavy Cotton Tee"')
    print_provider_id = models.IntegerField()

    # Display
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300)
    description = models.TextField(blank=True, help_text='HTML from Printify; trusted source (own shop)')
    tags = models.JSONField(default=list, blank=True)

    # Pricing — minimum enabled-variant price, used for "from $X" listing displays.
    # Actual line-item pricing always reads from Variant.price_cents.
    base_retail_price_cents = models.IntegerField(default=0)

    # Lifecycle
    is_published = models.BooleanField(
        default=True,
        help_text='Reflects Printify\'s "visible" flag. Hidden products are excluded from /shop/.',
    )
    sort_order = models.IntegerField(default=0)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['sort_order', 'title']
        unique_together = [('brand', 'slug')]
        indexes = [
            models.Index(fields=['brand', 'is_published']),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('catalog:product_detail', kwargs={'slug': self.slug})

    @property
    def default_image(self):
        """The image flagged is_default=True, falling back to the first by position."""
        return self.images.filter(is_default=True).first() or self.images.order_by('position').first()

    @property
    def display_price_cents(self):
        """Minimum enabled-variant price; falls back to base_retail_price_cents."""
        cheapest = (
            self.variants
            .filter(is_enabled=True, is_available=True)
            .order_by('price_cents')
            .values_list('price_cents', flat=True)
            .first()
        )
        return cheapest if cheapest is not None else self.base_retail_price_cents


class Variant(models.Model):
    """
    A (size, color) combination of a Product, with its own SKU and pricing.

    `is_enabled` toggles whether the variant is sold (controlled by Printify).
    `is_available` toggles whether Printify currently has stock for it.
    Both are False -> hidden from UI. is_enabled=False is also the soft-delete
    state when a variant is removed in Printify (preserves OrderItem references).
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants',
    )

    # Printify identifiers
    printify_variant_id = models.IntegerField()
    sku = models.CharField(max_length=100, blank=True)

    # Display
    title = models.CharField(max_length=200, help_text='e.g. "M / Black"')
    size = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=100, blank=True)

    # Pricing (cents)
    price_cents = models.IntegerField()
    cost_cents = models.IntegerField(default=0, help_text='What Printify charges us')

    # Lifecycle
    is_available = models.BooleanField(default=True, help_text='In stock at Printify')
    is_enabled = models.BooleanField(default=True, help_text='Listed for sale; False = soft-deleted')

    class Meta:
        ordering = ['product', 'size', 'color']
        unique_together = [('product', 'printify_variant_id')]
        indexes = [
            models.Index(fields=['product', 'is_enabled', 'is_available']),
        ]

    def __str__(self):
        return f'{self.product.title} — {self.title}'

    @property
    def is_for_sale(self):
        return self.is_enabled and self.is_available


class ProductImage(models.Model):
    """
    A Printify-hosted product image. We cache the URL only; image bytes stay
    on Printify's CDN (self-hosting is a 2.0 concern when bandwidth shows up).

    `variant_ids` is the list of Printify variant IDs this image represents,
    used so the UI can swap the main image when a variant is selected.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
    )
    url = models.URLField(max_length=500)
    is_default = models.BooleanField(default=False)
    position = models.IntegerField(default=0, help_text='Display order; lower first')
    variant_ids = models.JSONField(
        default=list,
        blank=True,
        help_text='Printify variant IDs (ints) this image represents.',
    )

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.product.title} image #{self.position}'
