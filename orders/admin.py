"""
Orders admin.

WebhookEvent (Sprint 2): read-only audit log.
Cart, CartItem (Sprint 3): mostly inspection-only \u2014 carts get created and
deleted by the cart views and the Stripe webhook, hand-editing them in admin
would just confuse the session state.
Order, OrderItem (Sprint 3): inspection + a few targeted admin actions.
Sprint 4 will add manual "resubmit to Printify" actions.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Cart, CartItem, Order, OrderItem, WebhookEvent


# =============================================================================
# WebhookEvent (Sprint 2, unchanged)
# =============================================================================

@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'source', 'event_type', 'event_id', 'processed_at', 'has_error')
    list_filter = ('source', 'event_type', 'processed_at')
    search_fields = ('event_id', 'event_type')
    readonly_fields = (
        'source',
        'event_id',
        'event_type',
        'payload',
        'received_at',
        'processed_at',
        'error',
    )
    ordering = ('-received_at',)

    @admin.display(boolean=True, description='Error?')
    def has_error(self, obj):
        return bool(obj.error)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Allow delete so John can clean up test events if needed.
        return True


# =============================================================================
# Cart + CartItem
# =============================================================================

class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    can_delete = True
    fields = ('variant', 'quantity', 'line_total_display', 'created_at')
    readonly_fields = ('variant', 'line_total_display', 'created_at')

    def line_total_display(self, obj):
        if obj.pk and obj.variant_id:
            return f'${obj.line_total_cents / 100:.2f}'
        return '\u2014'
    line_total_display.short_description = 'Line total'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'brand', 'session_key_short', 'item_count_display', 'subtotal_display', 'created_at', 'updated_at')
    list_filter = ('brand', 'created_at')
    search_fields = ('session_key', 'id')
    readonly_fields = ('brand', 'session_key', 'created_at', 'updated_at')
    ordering = ('-updated_at',)
    inlines = [CartItemInline]

    def session_key_short(self, obj):
        return (obj.session_key[:12] + '\u2026') if obj.session_key else '\u2014'
    session_key_short.short_description = 'Session'

    def item_count_display(self, obj):
        return obj.item_count
    item_count_display.short_description = 'Items'

    def subtotal_display(self, obj):
        return f'${obj.subtotal_cents / 100:.2f}'
    subtotal_display.short_description = 'Subtotal'

    def has_add_permission(self, request):
        # Carts are created by the cart views, not by hand.
        return False


# =============================================================================
# Order + OrderItem
# =============================================================================

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = (
        'thumbnail',
        'product_title',
        'variant_title',
        'quantity',
        'unit_price_display',
        'line_total_display',
    )
    readonly_fields = fields

    def thumbnail(self, obj):
        if not obj.image_url:
            return ''
        return format_html(
            '<img src="{}" style="height:48px; border-radius:4px;" loading="lazy">',
            obj.image_url,
        )
    thumbnail.short_description = ''

    def unit_price_display(self, obj):
        return f'${obj.unit_price_cents / 100:.2f}'
    unit_price_display.short_description = 'Unit'

    def line_total_display(self, obj):
        return f'${obj.line_total_cents / 100:.2f}'
    line_total_display.short_description = 'Line total'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'brand',
        'status',
        'email',
        'customer_name',
        'total_display',
        'printify_order_id_short',
        'created_at',
    )
    list_filter = ('brand', 'status', 'created_at')
    search_fields = (
        'email',
        'first_name',
        'last_name',
        'stripe_session_id',
        'stripe_payment_intent_id',
        'printify_order_id',
        'tracking_number',
        'id',
    )
    readonly_fields = (
        'brand',
        'stripe_session_id',
        'stripe_payment_intent_id',
        'subtotal_cents',
        'shipping_cents',
        'tax_cents',
        'total_cents',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        ('Order', {
            'fields': ('brand', 'status', 'created_at', 'updated_at'),
        }),
        ('Customer', {
            'fields': ('email', 'first_name', 'last_name', 'phone'),
        }),
        ('Shipping', {
            'fields': (
                'shipping_address_line_1',
                'shipping_address_line_2',
                'shipping_city',
                'shipping_state',
                'shipping_postal_code',
                'shipping_country',
                'shipping_method_code',
                'shipping_rate_label',
            ),
        }),
        ('Money (cents)', {
            'fields': ('subtotal_cents', 'shipping_cents', 'tax_cents', 'total_cents'),
        }),
        ('Stripe', {
            'fields': ('stripe_session_id', 'stripe_payment_intent_id'),
        }),
        ('Printify (Sprint 4)', {
            'fields': (
                'printify_order_id',
                'submitted_at',
                'submission_error',
            ),
        }),
        ('Fulfillment', {
            'fields': (
                'shipped_at',
                'delivered_at',
                'tracking_number',
                'tracking_url',
                'tracking_carrier',
            ),
        }),
    )
    inlines = [OrderItemInline]
    ordering = ('-created_at',)

    def total_display(self, obj):
        return f'${obj.total_cents / 100:.2f}'
    total_display.short_description = 'Total'

    def printify_order_id_short(self, obj):
        return obj.printify_order_id or '\u2014'
    printify_order_id_short.short_description = 'Printify ID'

    def has_add_permission(self, request):
        # Orders are created by the Stripe webhook, not by hand.
        return False
