from django.contrib import admin

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
