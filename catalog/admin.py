"""
Catalog admin — read-only registrations, plus publish/draft actions.

Products, Variants, and Images are cached from Printify; the sync command is the
only writer for their *content*. The change forms stay read-only (no
add/change/delete of fields from the UI).

Exception (Sprint 7): `Product.is_published` is a locally-owned draft/publish
flag, not a Printify mirror. It's toggled via the two changelist actions below
("Publish" / "Move to draft"), which write the field directly with .update() and
so are unaffected by it remaining in readonly_fields.
"""

from django.contrib import admin, messages
from django.utils.html import format_html

from brands.models import Brand

from .models import Product, ProductImage, Variant
from .printify_client import PrintifyError
from .services import clear_publish_locks, format_stats_summary, sync_brand_catalog


class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        'printify_variant_id',
        'title',
        'size',
        'color',
        'price_cents',
        'cost_cents',
        'is_available',
        'is_enabled',
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    can_delete = False
    fields = ('thumbnail', 'is_default', 'position', 'url')
    readonly_fields = fields

    def thumbnail(self, obj):
        if not obj.url:
            return ''
        return format_html(
            '<img src="{}" style="height:60px; border-radius:4px;" loading="lazy">',
            obj.url,
        )
    thumbnail.short_description = 'Preview'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'brand',
        'is_published',
        'variant_count',
        'display_price',
        'last_synced_at',
    )
    list_filter = ('brand', 'is_published')
    search_fields = ('title', 'slug', 'printify_product_id', 'tags')
    readonly_fields = (
        'brand',
        'printify_product_id',
        'blueprint_id',
        'print_provider_id',
        'title',
        'slug',
        'description',
        'tags',
        'base_retail_price_cents',
        'is_published',
        'sort_order',
        'created_at',
        'updated_at',
        'last_synced_at',
    )
    inlines = [VariantInline, ProductImageInline]
    actions = ('clear_locks', 'sync_from_printify', 'publish_products', 'unpublish_products')

    def variant_count(self, obj):
        return obj.variants.count()
    variant_count.short_description = 'Variants'

    def display_price(self, obj):
        cents = obj.display_price_cents
        return f'${cents / 100:.2f}' if cents else '—'
    display_price.short_description = 'From'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ---- Publish / draft actions -------------------------------------------
    # These are the "button" for John's one-click publish workflow. They write
    # is_published directly via .update(), which bypasses the change form — so
    # is_published can stay in readonly_fields (that only governs the form) while
    # still being toggleable here. Gated on 'change' permission; a superuser has
    # it, so the actions render in the changelist actions bar.
    @admin.action(description='Publish (show on site)', permissions=['change'])
    def publish_products(self, request, queryset):
        updated = queryset.update(is_published=True)
        self.message_user(
            request,
            f'{updated} product(s) published — now live on /shop/.',
            messages.SUCCESS,
        )

    @admin.action(description='Move to draft (hide)', permissions=['change'])
    def unpublish_products(self, request, queryset):
        updated = queryset.update(is_published=False)
        self.message_user(
            request,
            f'{updated} product(s) moved to draft — hidden from /shop/.',
            messages.WARNING,
        )

    # ---- Printify shop actions ---------------------------------------------
    # These two are shop-wide, not per-row: the selected products only pick which
    # brand/shop to target (with one brand, tick any one row).
    def _selected_brands(self, request, queryset):
        """Distinct Brand(s) of the selected products, or None (after messaging)."""
        brand_ids = list(queryset.values_list('brand_id', flat=True).distinct())
        brands = Brand.objects.filter(id__in=brand_ids)
        if not brands:
            self.message_user(
                request,
                'Select at least one product so I know which brand/shop to target.',
                messages.WARNING,
            )
            return None
        return brands

    # "Clear Printify publish locks" — the standalone unlock button. Walks every
    # product in the shop and calls publishing_succeeded to release any stuck
    # "Publishing…" cards so the design becomes editable again in Printify. This
    # is the admin equivalent of the shell loop over list_products +
    # publishing_succeeded. Touches Printify only; leaves the local catalog and
    # /shop/ visibility untouched.
    @admin.action(description='Clear Printify publish locks', permissions=['change'])
    def clear_locks(self, request, queryset):
        brands = self._selected_brands(request, queryset)
        if brands is None:
            return
        for brand in brands:
            try:
                stats = clear_publish_locks(brand)
            except ValueError as e:
                self.message_user(request, f'{brand.domain}: {e}', messages.ERROR)
                continue
            except PrintifyError as e:
                self.message_user(
                    request, f'{brand.domain}: Printify API error — {e}', messages.ERROR,
                )
                continue
            self.message_user(
                request,
                (
                    f'{brand.domain} — publish locks: {stats["acknowledged"]} released, '
                    f'{stats["skipped"]} not locked '
                    f'({stats["products_seen"]} products checked).'
                ),
                messages.SUCCESS,
            )

    # "Sync from Printify" — the standalone import button. Re-imports the catalog:
    # new products land as drafts (is_published=False); existing is_published
    # state is preserved. Does NOT clear locks (use "Clear Printify publish
    # locks") and does NOT publish to /shop/ (use "Publish (show on site)").
    @admin.action(description='Sync from Printify (import as drafts)', permissions=['change'])
    def sync_from_printify(self, request, queryset):
        brands = self._selected_brands(request, queryset)
        if brands is None:
            return
        for brand in brands:
            try:
                stats = sync_brand_catalog(brand)
            except ValueError as e:
                self.message_user(request, f'{brand.domain}: {e}', messages.ERROR)
                continue
            except PrintifyError as e:
                self.message_user(
                    request, f'{brand.domain}: Printify API error — {e}', messages.ERROR,
                )
                continue
            self.message_user(
                request,
                (
                    f'{brand.domain} — import: {format_stats_summary(stats)} '
                    f'(new products imported as drafts — publish them below).'
                ),
                messages.SUCCESS,
            )


@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'title',
        'size',
        'color',
        'price_cents',
        'is_available',
        'is_enabled',
    )
    list_filter = ('product__brand', 'is_available', 'is_enabled')
    search_fields = ('title', 'sku', 'product__title')
    readonly_fields = (
        'product',
        'printify_variant_id',
        'sku',
        'title',
        'size',
        'color',
        'price_cents',
        'cost_cents',
        'is_available',
        'is_enabled',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
