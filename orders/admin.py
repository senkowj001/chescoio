"""
Orders admin.

WebhookEvent (Sprint 2): read-only audit log.
Cart, CartItem (Sprint 3): mostly inspection-only \u2014 carts get created and
deleted by the cart views and the Stripe webhook, hand-editing them in admin
would just confuse the session state.
Order, OrderItem (Sprint 3): inspection + a few targeted admin actions.
Sprint 4 adds a "Retry Printify submission" action for orders stuck in
submission_failed, plus a read-only panel showing recent Printify webhook
activity related to the order.
"""

from django.contrib import admin, messages
from django.urls import reverse
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
        'lookup_token',
        'lookup_link',
        'stripe_session_id',
        'stripe_payment_intent_id',
        'subtotal_cents',
        'shipping_cents',
        'tax_cents',
        'total_cents',
        'refunded_cents',
        'refunded_at',
        'created_at',
        'updated_at',
        'confirmation_sent_at',
        'shipped_email_sent_at',
        'recent_webhook_events',
    )
    fieldsets = (
        ('Order', {
            'fields': ('brand', 'status', 'lookup_token', 'lookup_link', 'created_at', 'updated_at'),
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
        ('Refunds (Sprint 5)', {
            'fields': ('refunded_cents', 'refunded_at'),
            'description': (
                'Populated by the Stripe charge.refunded webhook. A full refund '
                'also flips status to “refunded”; a partial refund records the '
                'amount only. Refunds are issued in the Stripe dashboard — this '
                'panel is read-only. Printify does NOT auto-refund: to recover '
                'fulfillment cost on a refunded order, open a Printify support '
                'ticket separately.'
            ),
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
        ('Email notifications (Sprint 4)', {
            'fields': ('confirmation_sent_at', 'shipped_email_sent_at'),
        }),
        ('Webhook activity (Sprint 4)', {
            'fields': ('recent_webhook_events',),
        }),
    )
    inlines = [OrderItemInline]
    ordering = ('-created_at',)
    actions = ['retry_printify_submission']

    def total_display(self, obj):
        return f'${obj.total_cents / 100:.2f}'
    total_display.short_description = 'Total'

    def printify_order_id_short(self, obj):
        return obj.printify_order_id or '\u2014'
    printify_order_id_short.short_description = 'Printify ID'

    def has_add_permission(self, request):
        # Orders are created by the Stripe webhook, not by hand.
        return False

    def lookup_link(self, obj):
        """Clickable link to the customer-facing public order-status page."""
        if not obj.pk or not obj.lookup_token:
            return format_html('&mdash;')
        path = reverse('orders:order_status', kwargs={'lookup_token': obj.lookup_token})
        url = f'https://{obj.brand.domain}{path}'
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, url)
    lookup_link.short_description = 'Public status page'

    def recent_webhook_events(self, obj):
        """
        Read-only panel of the most recent Printify WebhookEvent rows that
        reference this order's printify_order_id. There's no FK from
        WebhookEvent to Order (the payload is the only link), so this is a
        best-effort text search over the stored JSON payload rather than a
        real join.
        """
        if not obj.pk or not obj.printify_order_id:
            return 'No Printify order ID yet.'
        try:
            events = list(
                WebhookEvent.objects.filter(
                    source=WebhookEvent.SOURCE_PRINTIFY,
                    payload__icontains=obj.printify_order_id,
                ).order_by('-received_at')[:10]
            )
        except Exception:
            # Some DB backends don't support icontains on JSONField the same
            # way; degrade gracefully rather than breaking the admin page.
            events = []
        if not events:
            return 'No related webhook events recorded yet.'
        rows = []
        for e in events:
            flag = f' — error: {e.error[:80]}' if e.error else ''
            rows.append(
                f'<div style="padding:2px 0;">'
                f'<strong>{e.event_type}</strong> '
                f'<span style="color:#78716c;">{e.received_at:%Y-%m-%d %H:%M:%S}</span>'
                f'{flag}'
                f'</div>'
            )
        return format_html(''.join(rows))
    recent_webhook_events.short_description = 'Recent Printify webhook events'

    @admin.action(description='Retry Printify submission')
    def retry_printify_submission(self, request, queryset):
        """
        Force-resubmit selected orders to Printify, bypassing the normal
        status==paid guard in submit_order_to_printify. Only meaningful for
        orders currently in submission_failed — anything else is skipped so
        this action can't accidentally double-submit an order that's already
        progressing through fulfillment.

        Common fix-then-retry flow: correct the shipping address or other
        field in this admin page, save, select the order, run this action.
        """
        from .checkout_services import submit_order_to_printify  # local import avoids a cycle

        succeeded, skipped = 0, 0
        for order in queryset:
            if order.status != Order.STATUS_SUBMISSION_FAILED:
                skipped += 1
                continue
            submit_order_to_printify(order, force=True)
            order.refresh_from_db()
            if order.status == Order.STATUS_SUBMITTED:
                succeeded += 1

        if succeeded:
            self.message_user(
                request, f'{succeeded} order(s) resubmitted successfully.', level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f'{skipped} order(s) skipped (not in submission_failed status).',
                level=messages.WARNING,
            )
        still_failed = queryset.filter(status=Order.STATUS_SUBMISSION_FAILED).count()
        if still_failed:
            self.message_user(
                request,
                f'{still_failed} order(s) still failed — check submission_error for details.',
                level=messages.ERROR,
            )
