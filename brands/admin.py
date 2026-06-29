from django.contrib import admin, messages

from catalog.printify_client import PrintifyError
from catalog.services import format_stats_summary, sync_brand_catalog

from .models import Brand


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'domain', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'domain', 'tagline')
    readonly_fields = ('created_at',)

    fieldsets = (
        ('Identity', {
            'fields': ('name', 'domain', 'tagline', 'description', 'is_active'),
        }),
        ('Theme', {
            'fields': ('primary_color', 'accent_color', 'logo_url', 'font_family'),
        }),
        ('Printify', {
            'fields': ('printify_shop_id',),
        }),
        ('Analytics / tracking', {
            'fields': ('meta_pixel_id', 'plausible_domain'),
        }),
        ('Email', {
            'fields': ('from_email', 'support_email'),
        }),
        ('Metadata', {
            'fields': ('created_at',),
        }),
    )

    # -------------------------------------------------------------------------
    # Sprint 3 deliverable #11: admin "Sync Now" action.
    #
    # Calls catalog.services.sync_brand_catalog directly for each selected
    # brand. Synchronous \u2014 fine at the current product volume (<50 products,
    # ~10-15s well under Heroku's 30s request timeout). When the catalog grows
    # past ~100 products, revisit with a background queue.
    #
    # Concurrency with the hourly Heroku Scheduler run is safe: the underlying
    # update_or_create semantics tolerate overlap. Worst case is a handful of
    # redundant API calls and writes \u2014 no corruption.
    # -------------------------------------------------------------------------

    actions = ['sync_printify_products_now']

    @admin.action(description='Sync Printify products now')
    def sync_printify_products_now(self, request, queryset):
        for brand in queryset:
            if not brand.printify_shop_id:
                self.message_user(
                    request,
                    f'{brand.name}: skipped (no printify_shop_id set).',
                    level=messages.WARNING,
                )
                continue
            try:
                stats = sync_brand_catalog(brand)
            except PrintifyError as exc:
                self.message_user(
                    request,
                    f'{brand.name}: Printify API error \u2014 {exc}',
                    level=messages.ERROR,
                )
                continue
            except ValueError as exc:
                self.message_user(
                    request,
                    f'{brand.name}: {exc}',
                    level=messages.ERROR,
                )
                continue
            except Exception as exc:  # noqa: BLE001 \u2014 admin action must not 500
                self.message_user(
                    request,
                    f'{brand.name}: sync failed \u2014 {exc}',
                    level=messages.ERROR,
                )
                continue

            level = messages.SUCCESS if not stats['products_failed'] else messages.WARNING
            self.message_user(
                request,
                f'{brand.name}: {format_stats_summary(stats)}',
                level=level,
            )
