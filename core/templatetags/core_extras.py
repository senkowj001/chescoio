"""
Core template filters.

`markdownify`: render a StaticPage's Markdown body to HTML.

StaticPage content is authored by staff through the admin, so it's a trusted
source — the same trust model the catalog already applies when it renders
Printify product descriptions with |safe. We therefore render the Markdown to
HTML and mark it safe rather than escaping it, which is what lets a page author
use the occasional inline HTML snippet when Markdown isn't enough.

The Markdown package is an ordinary third-party dependency (see
requirements.txt). If for some reason it isn't installed in the running
environment, the filter degrades to escaped, line-broken plain text instead of
raising — a legal or marketing page rendering as plain text is a far better
failure than a 500.
"""

from django import template
from django.utils.html import escape, linebreaks
from django.utils.safestring import mark_safe

register = template.Library()

# Markdown extensions:
#   extra      - tables, fenced code, definition lists, etc. (needed for the
#                size-guide tables)
#   sane_lists - predictable list parsing
#   nl2br      - single newlines become <br>, so authors don't have to think
#                about Markdown's double-space line-break rule
#   smarty     - straight quotes/dashes become typographic ones
_MD_EXTENSIONS = ['extra', 'sane_lists', 'nl2br', 'smarty']


@register.filter(name='markdownify')
def markdownify(value):
    """
    Render Markdown text to safe HTML.

    Usage:
        {{ page.content|markdownify }}

    Falls back to escaped, line-broken text if the Markdown package is
    unavailable, so a page never 500s on a rendering dependency.
    """
    if not value:
        return ''
    try:
        import markdown
    except ImportError:
        return mark_safe(linebreaks(escape(value)))

    html = markdown.markdown(
        str(value),
        extensions=_MD_EXTENSIONS,
        output_format='html5',
    )
    return mark_safe(html)


@register.simple_tag(takes_context=True)
def published_page_slugs(context):
    """
    Return the set of published StaticPage slugs for the current brand.

    The footer uses this to render legal/marketing links only for pages that
    are actually live — so links to still-unpublished legal drafts don't 404
    for the public before John has approved and published them. A page appears
    in the footer the moment it's published, with no template change. Returns
    an empty set when there's no request/brand (e.g. an error page rendered
    without a resolved brand).
    """
    from .models import StaticPage  # local import keeps this module import-light
    request = context.get('request')
    brand = getattr(request, 'brand', None) if request else None
    if brand is None:
        return set()
    return set(
        StaticPage.objects
        .filter(brand=brand, is_published=True)
        .values_list('slug', flat=True)
    )
