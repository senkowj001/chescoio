from django.db import models


class Brand(models.Model):
    """
    A tenant brand front for the chescoio multi-brand apparel platform.

    BrandMiddleware resolves the active brand from request.get_host(), so
    one Heroku app can serve multiple brand domains. All Product, Order, and
    related records are scoped to a Brand.
    """

    # Identity
    domain = models.CharField(
        max_length=255,
        unique=True,
        help_text='Bare apex domain, e.g. "chesco.io". www is stripped before lookup.',
    )
    name = models.CharField(max_length=100)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)

    # Printify
    printify_shop_id = models.CharField(max_length=50, blank=True)

    # Theme — referenced from base.html as CSS variables
    primary_color = models.CharField(max_length=7, default='#000000')
    accent_color = models.CharField(max_length=7, default='#FF6B35')
    logo_url = models.URLField(blank=True)
    font_family = models.CharField(max_length=100, default='Inter')

    # Analytics / tracking
    meta_pixel_id = models.CharField(max_length=50, blank=True)
    plausible_domain = models.CharField(max_length=255, blank=True)

    # Email
    from_email = models.EmailField()
    support_email = models.EmailField()

    # Lifecycle
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
