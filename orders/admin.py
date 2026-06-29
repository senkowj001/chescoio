"""
Orders admin.

WebhookEvent registered read-only — these are an audit trail and should not be
hand-edited. Cart / Order admin registrations land in Sprint 3+.
"""

from django.contrib import admin

from .models import WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'source', 'event_type', 'event_id', 'processed_at')
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

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Allow delete so John can clean up test events if needed.
        return True
