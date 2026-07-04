"""
Core views (Sprint 5).

Homepage (Sprints 1-4) plus the Sprint 5 marketing / legal / SEO surface:

  static_page   -- markdown CMS pages (about, privacy, terms, returns,
                   shipping, size-guide, and /p/<slug>/ one-offs). Unpublished
                   pages 404 for the public but preview for logged-in staff.
  contact       -- HTMX contact form: validates, honeypot-guards, logs a
                   ContactMessage, emails brand.support_email.
  email_signup  -- HTMX footer signup: dedupes into EmailSignup.
  robots_txt    -- dynamic robots.txt pointing at the sitemap.
  sitemap       -- brand-scoped sitemap.xml via Django's sitemaps framework.
  page_not_found / server_error -- branded 404 / 500 handlers.

Everything is brand-scoped via request.brand (BrandMiddleware). The mailer
calls queue through django-mailer (EMAIL_BACKEND = DbBackend), same as the
order emails.
"""

import logging

from django.contrib import messages
from django.contrib.sitemaps.views import sitemap as sitemap_view
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.template import loader
from django.views.decorators.http import require_http_methods, require_POST

from mailer import send_mail

from .models import ContactMessage, EmailSignup, StaticPage
from .sitemaps import ProductSitemap, StaticPageSitemap, StaticViewSitemap

logger = logging.getLogger(__name__)

# Honeypot field name shared by the contact and signup forms. A real browser
# leaves it empty (it's visually hidden); bots that fill every field trip it.
HONEYPOT_FIELD = 'company'


def _brand_or_404(request):
    """Raise 404 if BrandMiddleware didn't resolve a brand. View-level guard."""
    brand = getattr(request, 'brand', None)
    if brand is None:
        raise Http404('No brand resolved for this host.')
    return brand


def _is_htmx(request) -> bool:
    return request.headers.get('HX-Request') == 'true'


# =============================================================================
# Homepage
# =============================================================================

def home(request):
    """
    Brand-aware homepage. Renders copy from request.brand.

    Intentionally minimal and stable across sprints; brand fields drive the
    content so a second brand front needs no code change.
    """
    return render(request, 'home.html')


# =============================================================================
# Static (markdown CMS) pages
# =============================================================================

def static_page(request, slug):
    """
    Render a StaticPage by slug for the current brand.

    404 if the page doesn't exist. If it exists but isn't published, it 404s
    for the public and renders with a draft banner for logged-in staff, so
    John can preview legal copy before flipping is_published.
    """
    brand = _brand_or_404(request)

    page = StaticPage.objects.filter(brand=brand, slug=slug).first()
    if page is None:
        raise Http404('No such page.')

    if not page.is_published and not request.user.is_staff:
        raise Http404('Page not published.')

    is_draft_preview = not page.is_published  # only reachable here if staff
    return render(request, 'core/static_page.html', {
        'page': page,
        'is_draft_preview': is_draft_preview,
    })


# =============================================================================
# Contact form
# =============================================================================

def contact(request):
    """
    GET  /contact/  -- render the contact form.
    POST /contact/  -- validate, honeypot-check, persist a ContactMessage,
                       email brand.support_email, and return a thank-you.

    HTMX posts swap the #contact-form-wrap inner content (form -> success, or
    form -> form-with-errors). Non-HTMX posts re-render the full page.
    """
    brand = _brand_or_404(request)

    if request.method == 'GET':
        return render(request, 'core/contact.html', {})

    # --- POST ---
    name = (request.POST.get('name') or '').strip()
    email = (request.POST.get('email') or '').strip()
    message = (request.POST.get('message') or '').strip()
    honeypot = (request.POST.get(HONEYPOT_FIELD) or '').strip()

    # Honeypot tripped -> almost certainly a bot. Pretend success (don't give
    # the bot a signal) but persist nothing and send nothing.
    if honeypot:
        logger.info('contact: honeypot tripped for brand=%s; dropping.', brand.domain)
        return _contact_success_response(request)

    errors = {}
    if not name:
        errors['name'] = 'Please tell us your name.'
    if not email:
        errors['email'] = 'Please enter your email so we can reply.'
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors['email'] = 'That doesn\u2019t look like a valid email address.'
    if not message:
        errors['message'] = 'Please enter a message.'

    if errors:
        return _contact_form_response(
            request,
            errors=errors,
            values={'name': name, 'email': email, 'message': message},
            status=422,
        )

    ContactMessage.objects.create(
        brand=brand,
        name=name,
        email=email,
        message=message,
    )

    # Notify support. Queued via django-mailer; failure to queue shouldn't
    # lose the message (already persisted above) or 500 the request.
    try:
        send_mail(
            subject=f'[{brand.name}] Contact form: {name}',
            message=(
                f'New contact form submission on {brand.domain}:\n\n'
                f'Name:  {name}\n'
                f'Email: {email}\n\n'
                f'Message:\n{message}\n'
            ),
            from_email=brand.from_email,
            recipient_list=[brand.support_email],
        )
    except Exception:
        logger.exception('contact: failed to queue notification email for brand=%s', brand.domain)

    logger.info('contact: message received for brand=%s from %s', brand.domain, email)
    return _contact_success_response(request)


def _contact_form_response(request, *, errors=None, values=None, status=200):
    ctx = {'errors': errors or {}, 'values': values or {}}
    if _is_htmx(request):
        return render(request, 'core/_contact_form.html', ctx, status=status)
    return render(request, 'core/contact.html', ctx, status=status)


def _contact_success_response(request):
    if _is_htmx(request):
        return render(request, 'core/_contact_success.html', {})
    return render(request, 'core/contact.html', {'sent': True})


# =============================================================================
# Email signup (footer)
# =============================================================================

@require_POST
def email_signup(request):
    """
    POST /signup/ -- add an email to the brand's new-release list.

    Deduped per (brand, email). HTMX posts swap in a thank-you fragment;
    non-HTMX posts redirect back with a message.
    """
    brand = _brand_or_404(request)

    email = (request.POST.get('email') or '').strip().lower()
    source = (request.POST.get('source') or EmailSignup.SOURCE_FOOTER).strip()
    honeypot = (request.POST.get(HONEYPOT_FIELD) or '').strip()

    if source not in dict(EmailSignup.SOURCE_CHOICES):
        source = EmailSignup.SOURCE_FOOTER

    # Honeypot -> pretend success, persist nothing.
    if honeypot:
        logger.info('email_signup: honeypot tripped for brand=%s; dropping.', brand.domain)
        return _signup_response(request, ok=True)

    valid = True
    try:
        validate_email(email)
    except ValidationError:
        valid = False

    if not valid:
        return _signup_response(request, ok=False)

    EmailSignup.objects.get_or_create(
        brand=brand,
        email=email,
        defaults={'source': source},
    )
    logger.info('email_signup: %s joined the %s list (source=%s)', email, brand.domain, source)
    return _signup_response(request, ok=True)


def _signup_response(request, *, ok: bool):
    if _is_htmx(request):
        status = 200 if ok else 422
        return render(request, 'core/_email_signup_success.html', {'ok': ok}, status=status)
    if ok:
        messages.success(request, 'Thanks for signing up! We\u2019ll be in touch with new releases.')
    else:
        messages.warning(request, 'That email didn\u2019t look valid \u2014 please try again.')
    return redirect(request.META.get('HTTP_REFERER') or 'core:home')


# =============================================================================
# robots.txt + sitemap.xml
# =============================================================================

def robots_txt(request):
    """
    Dynamic robots.txt: allow crawling of public pages, disallow the
    transactional / private paths, and point at the sitemap.
    """
    sitemap_url = request.build_absolute_uri('/sitemap.xml')
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin/',
        'Disallow: /cart/',
        'Disallow: /checkout/',
        'Disallow: /webhooks/',
        'Disallow: /orders/',
        '',
        f'Sitemap: {sitemap_url}',
        '',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')


def sitemap(request):
    """
    Brand-scoped sitemap.xml.

    Builds the sitemap set for request.brand and delegates to Django's
    sitemaps framework view. The framework derives the host from the request
    (django.contrib.sites is not installed), so URLs are brand-correct; each
    sitemap forces https via its protocol attribute.
    """
    brand = _brand_or_404(request)
    maps = {
        'static': StaticViewSitemap(brand),
        'products': ProductSitemap(brand),
        'pages': StaticPageSitemap(brand),
    }
    return sitemap_view(request, sitemaps=maps)


# =============================================================================
# Error handlers (wired in chescoio/urls.py)
# =============================================================================

def page_not_found(request, exception=None):
    """
    Branded 404 for a page-not-found within a valid brand. (The
    unknown-hostname 404 is handled separately by BrandMiddleware rendering
    brands/not_found.html.) Extends base.html, so it's brand-themed.
    """
    return render(request, '404.html', {}, status=404)


def server_error(request):
    """
    Branded 500.

    Rendered via loader.render_to_string with an explicit context rather than
    render(), so it does NOT run context processors (the cart context
    processor touches the DB, which may be exactly what's broken during a
    500). 500.html is self-contained for the same reason. Falls back to a
    bare HTML string if even that fails.
    """
    brand = getattr(request, 'brand', None)
    try:
        html = loader.render_to_string('500.html', {'brand': brand})
        return HttpResponse(html, status=500)
    except Exception:
        logger.exception('server_error: 500.html failed to render; using bare fallback.')
        return HttpResponse(
            '<!doctype html><html><head><meta charset="utf-8">'
            '<title>Something went wrong</title></head>'
            '<body style="font-family:system-ui,sans-serif;max-width:40rem;'
            'margin:4rem auto;padding:0 1.5rem;color:#1c1c1c;">'
            '<h1>Something went wrong</h1>'
            '<p>We hit an unexpected error. Please try again in a moment.</p>'
            '</body></html>',
            status=500,
            content_type='text/html',
        )
