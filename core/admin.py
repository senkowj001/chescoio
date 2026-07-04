"""
Core admin (Sprint 5).

StaticPage is the one John edits routinely: markdown CMS pages, with
is_published gating public visibility and needs_review as a draft/sign-off
checklist flag. ContactMessage and EmailSignup are inspection surfaces
(contact log + newsletter list) with light triage actions.
"""

from django.contrib import admin, messages

from .models import ContactMessage, EmailSignup, StaticPage


@admin.register(StaticPage)
class StaticPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'brand', 'slug', 'is_published', 'needs_review', 'updated_at')
    list_filter = ('brand', 'is_published', 'needs_review')
    search_fields = ('title', 'slug', 'content')
    list_editable = ('is_published', 'needs_review')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('brand', 'title', 'slug', 'content'),
        }),
        ('SEO', {
            'fields': ('meta_description',),
        }),
        ('Publishing', {
            'fields': ('is_published', 'needs_review', 'sort_order'),
            'description': (
                'Unpublished pages 404 for the public but preview for staff. '
                '\u201cNeeds review\u201d is a checklist flag only \u2014 uncheck it once '
                'you\u2019ve approved the copy, then publish.'
            ),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.action(description='Mark selected pages published')
    def mark_published(self, request, queryset):
        updated = queryset.update(is_published=True)
        self.message_user(request, f'{updated} page(s) published.', level=messages.SUCCESS)

    @admin.action(description='Mark selected pages unpublished')
    def mark_unpublished(self, request, queryset):
        updated = queryset.update(is_published=False)
        self.message_user(request, f'{updated} page(s) unpublished.', level=messages.WARNING)

    @admin.action(description='Clear \u201cneeds review\u201d flag')
    def clear_needs_review(self, request, queryset):
        updated = queryset.update(needs_review=False)
        self.message_user(request, f'{updated} page(s) marked reviewed.', level=messages.SUCCESS)

    actions = ['mark_published', 'mark_unpublished', 'clear_needs_review']


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'brand', 'name', 'email', 'is_handled')
    list_filter = ('brand', 'is_handled', 'created_at')
    search_fields = ('name', 'email', 'message')
    list_editable = ('is_handled',)
    readonly_fields = ('brand', 'name', 'email', 'message', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    @admin.action(description='Mark selected as handled')
    def mark_handled(self, request, queryset):
        updated = queryset.update(is_handled=True)
        self.message_user(request, f'{updated} message(s) marked handled.', level=messages.SUCCESS)

    actions = ['mark_handled']


@admin.register(EmailSignup)
class EmailSignupAdmin(admin.ModelAdmin):
    list_display = ('email', 'brand', 'source', 'is_confirmed', 'created_at')
    list_filter = ('brand', 'source', 'is_confirmed', 'created_at')
    search_fields = ('email',)
    readonly_fields = ('brand', 'email', 'source', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False
