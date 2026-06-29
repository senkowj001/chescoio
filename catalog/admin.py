"""
Catalog admin — read-only registrations.

Products, Variants, and Images are owned by Printify; the sync command is the
only writer. Admin is for inspection only — no add/change/delete from the UI.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Product, ProductImage, Variant


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
