# East Goshen Apparel Platform — Build Plan

**Project:** Multi-brand print-on-demand apparel storefront, Django backend
**First brand front:** chesco.io (Chester County, PA local-pride apparel)
**Architecture:** Single Django app, multi-brand via hostname routing, shared Printify/Stripe backend
**Target launch:** End of Sprint 5 (~5-6 weekends of focused work)

---

## Strategic context (read this first)

This is the operational follow-through on the East Goshen Technologies SaaS portfolio thesis: modern stack, AI-leveraged velocity, zero technical debt, low overhead, niche distribution. The apparel platform is the passion-project lane — designed to run cheaply, scratch a creative itch, and serve as a marketing surface for local brand equity. It is **not** the main revenue play and should never be treated with the same intensity as a SaaS launch.

**Operating principles:**
- Reuse aggressively from HuntScrape, Apeirum, and Honey & Pine patterns. Do not reinvent what's already in production.
- Build for multi-brand from day one. Adding brand #2 later should be a configuration change, not a refactor.
- Guest checkout only for v1. No customer accounts, no allauth on the customer side.
- Skip product photography for v1; use Printify mockups. Real photography is a 2.0 pursuit.
- Stripe Tax handles sales tax. Do not write custom tax logic.
- Single Heroku app, subdomain routing, brand-aware theming.

**Stack lock:**
- Django 5.x, PostgreSQL (Heroku Postgres Essential-0), Python 3.12
- HTMX + Tailwind via CDN (mirror HuntScrape pattern, no local build pipeline)
- Stripe Checkout (hosted, with Stripe Tax enabled)
- Printify REST API
- django-mailer for async email (mirror HuntScrape pattern)
- Cloudflare in front
- Plausible analytics
- Meta Pixel for ad tracking (mirror HuntScrape pattern)
- Heroku Scheduler for nightly Printify product sync

---

## Architectural decisions, locked

### Multi-brand model

A `Brand` model is the tenant. Each brand has:
- `domain` (e.g., `chesco.io`)
- `name`, `tagline`, `description`
- `printify_shop_id` (each brand can have its own Printify shop, or share)
- `stripe_account_id` (single Stripe account for v1; Stripe Connect is a 2.0 concern)
- `theme_config` (JSON: primary color, accent, font choice, logo URL)
- `meta_pixel_id`, `plausible_domain`
- `from_email`, `support_email`
- `is_active` boolean

Middleware resolves `request.brand` from `request.get_host()`. All views, templates, and queries scope to `request.brand`. This is the same pattern HuntScrape uses for `Tenant`; copy it.

### Order pipeline

```
Customer cart → Stripe Checkout (with Stripe Tax + dynamic shipping)
  → Stripe webhook (checkout.session.completed) → Create local Order, status=paid
  → Submit order to Printify API → Store printify_order_id, status=submitted
  → Printify webhook (order:sent-to-production) → status=in_production, send email
  → Printify webhook (order:shipment:created) → status=shipped, send email with tracking
  → Printify webhook (order:shipment:delivered) → status=delivered
```

### Models inventory (final list for v1)

- `Brand` — multi-brand config
- `Product` — local cache of Printify product, scoped to Brand
- `Variant` — size/color combos, with Printify variant ID
- `ProductImage` — cached image URLs from Printify
- `Cart` — session-keyed, expires after 7 days
- `CartItem` — variant + quantity
- `Order` — final order record, scoped to Brand
- `OrderItem` — line items
- `EmailSignup` — for the "drop your email for new releases" form
- `WebhookEvent` — audit log of every Stripe + Printify webhook received (idempotency)

---

# Sprint 1 — Foundation & Multi-Brand Scaffolding

**Goal:** A deployed Django app on Heroku, multi-brand routing working, admin can create brands, no products yet.

**Estimated time:** 8-12 hours

## Sprint 1 deliverables

1. New Django project `eg_apparel` initialized, pushed to GitHub
2. Heroku app provisioned with Postgres Essential-0, deployed from main branch
3. Custom domain `chesco.io` pointed at Heroku via Cloudflare (DNS, SSL, proxy on)
4. `Brand` model created with admin registration
5. `BrandMiddleware` resolves `request.brand` from hostname
6. Base template renders brand name, tagline, theme colors from `request.brand`
7. Homepage view exists at `/` showing brand-aware "Coming soon" page
8. 404 handler for unknown hostnames (no matching `Brand`)
9. Settings configured for: Heroku Postgres, Cloudflare-aware `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT` gated on `DEBUG=False` (apply the fix you learned on HuntScrape)
10. django-mailer installed and configured (no emails sent yet, just plumbing)
11. Plausible script tag conditionally rendered if brand has `plausible_domain`
12. Meta Pixel base code conditionally rendered if brand has `meta_pixel_id`

## Sprint 1 implementation steps

### 1.1 Project skeleton

```bash
django-admin startproject eg_apparel
cd eg_apparel
python manage.py startapp brands
python manage.py startapp catalog  # placeholder for sprint 2
python manage.py startapp orders   # placeholder for sprint 3
python manage.py startapp core     # shared utilities
```

Mirror the HuntScrape settings layout: `settings/base.py`, `settings/dev.py`, `settings/prod.py`. Use `dj_database_url`, `django-environ` or equivalent for env var loading.

### 1.2 Brand model

```python
# brands/models.py
class Brand(models.Model):
    domain = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=100)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)

    # Printify
    printify_shop_id = models.CharField(max_length=50, blank=True)

    # Theme
    primary_color = models.CharField(max_length=7, default="#000000")
    accent_color = models.CharField(max_length=7, default="#FF6B35")
    logo_url = models.URLField(blank=True)
    font_family = models.CharField(max_length=100, default="Inter")

    # Tracking
    meta_pixel_id = models.CharField(max_length=50, blank=True)
    plausible_domain = models.CharField(max_length=255, blank=True)

    # Email
    from_email = models.EmailField()
    support_email = models.EmailField()

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
```

### 1.3 Brand middleware

```python
# brands/middleware.py
from django.shortcuts import render
from .models import Brand

class BrandMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0].lower()
        # Strip www.
        if host.startswith("www."):
            host = host[4:]
        try:
            request.brand = Brand.objects.get(domain=host, is_active=True)
        except Brand.DoesNotExist:
            request.brand = None
            if not request.path.startswith("/admin"):
                return render(request, "brands/not_found.html", status=404)
        return self.get_response(request)
```

Add to `MIDDLEWARE` after `SecurityMiddleware`, before any view-dispatching middleware.

### 1.4 Base template with brand context

```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}{{ request.brand.name }}{% endblock %}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@2.0.3"></script>
    <style>
        :root {
            --brand-primary: {{ request.brand.primary_color }};
            --brand-accent: {{ request.brand.accent_color }};
        }
    </style>
    {% if request.brand.plausible_domain %}
        <script defer data-domain="{{ request.brand.plausible_domain }}"
                src="https://plausible.io/js/script.js"></script>
    {% endif %}
    {% if request.brand.meta_pixel_id %}
        <!-- Meta Pixel base code, parameterized by request.brand.meta_pixel_id -->
    {% endif %}
</head>
<body>
    {% include "partials/header.html" %}
    {% block content %}{% endblock %}
    {% include "partials/footer.html" %}
</body>
</html>
```

### 1.5 Heroku setup

```bash
heroku create eg-apparel
heroku addons:create heroku-postgresql:essential-0
heroku addons:create scheduler:standard
heroku config:set DJANGO_SETTINGS_MODULE=eg_apparel.settings.prod
heroku config:set SECRET_KEY=...
heroku config:set ALLOWED_HOSTS=chesco.io,eg-apparel.herokuapp.com
heroku buildpacks:set heroku/python
```

`Procfile`:
```
web: gunicorn eg_apparel.wsgi --log-file -
release: python manage.py migrate
```

### 1.6 Cloudflare DNS

- A record `chesco.io` → Heroku DNS target (from `heroku domains:add chesco.io`)
- CNAME `www.chesco.io` → `chesco.io`
- SSL mode: Full (strict)
- Always Use HTTPS: on
- Apply the SSL redirect fix you discovered on HuntScrape: `SECURE_SSL_REDIRECT = not DEBUG` gated properly

### 1.7 Seed first brand

```python
# In Django shell or a data migration
Brand.objects.create(
    domain="chesco.io",
    name="Chesco",
    tagline="Made for the 610.",
    description="Apparel for people who live, work, and play in Chester County.",
    primary_color="#1a4d2e",
    accent_color="#f4a261",
    from_email="hello@chesco.io",
    support_email="hello@chesco.io",
)
```

## Sprint 1 acceptance criteria

- [ ] Visiting `https://chesco.io` returns a 200 with the brand name and tagline rendered
- [ ] Visiting `https://unknown-domain.com` (if pointed at the app) returns a 404 "brand not found" page
- [ ] Django admin at `/admin/` works and shows the Brand model
- [ ] SSL redirect works in production, doesn't fire in dev
- [ ] No console errors on the homepage
- [ ] `python manage.py check --deploy` returns clean

## Sprint 1 — delivery notes (deviations from plan as written)

Documented at end of Sprint 1 so the plan stays the source of truth for Sprints 2-5.

- **Project module is `chescoio`, not `eg_apparel`.** Heroku app is `chescoio`. GitHub repo is `chescoio`. Project lives at `C:\django\prod-django\chescoio\` per portfolio convention. Multi-brand architecture is unaffected — routing lives in the `Brand` model and `BrandMiddleware`, not in the project module name. If brand #2 ever launches, the project module name stays `chescoio` (cosmetic).
- **Site headline (Brand.name) is `Chester County Apparel Co.`**, not `Chesco`. Tagline `Made for the 610.` and other seed values per plan.
- **No staging environment.** Dev → prod direct via `main` branch. Supersedes Operating Rule #1 ("Stage before production"). Acceptable risk for a zero-user passion project; revisit with a Heroku pipeline if/when chesco draws meaningful traffic.
- **No Cloudflare.** DNS via Hostinger (manual CNAME setup by John). `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` still applies — Heroku's router terminates SSL and sets that header. Sprint 5 deliverable #12 (Cloudflare WAF rules) is **deleted**.
- **Django pinned to 5.2.12 LTS**, not the 6.0.6 the project was scaffolded with. Matches HuntScrape and the rest of the portfolio. Plan's stack lock said `Django 5.x`; this confirms 5.2.x line.
- **Settings filenames are `local.py` / `production.py`**, not the plan's `dev.py` / `prod.py`. Mirrors HuntScrape's naming.
- **Tailwind v4 via `@tailwindcss/browser@4`** with `@theme` design tokens (Honey & Pine pattern), not the v3 `cdn.tailwindcss.com` script the plan's 1.4 example showed. Brand colors flow through as CSS variables `--color-brand-primary` and `--color-brand-accent`, which Tailwind v4 surfaces as utility classes (`bg-brand-primary`, `text-brand-accent`, etc.).
- **`BrandMiddleware` has a DEBUG fallback** beyond the plan: in dev, unknown hosts resolve to the first active Brand so `localhost:8000` works without hosts-file gymnastics. Production behavior (strict 404 for unknown hosts, except `/admin/`) is unchanged.
- **`Procfile` release phase runs `collectstatic --noinput` in addition to `migrate --noinput`.** Matches HuntScrape's belt-and-suspenders pattern; the Python buildpack also runs collectstatic during build, so this is redundant but explicit.
- **One unrelated cleanup left for John:** delete `C:\django\chescoio\` (now empty) and `chescoio\_old_settings.py.bak` once verified. Neither can be removed via the MCP filesystem (no delete tool).

---

# Sprint 2 — Printify Integration

**Goal:** Products sync from Printify to local DB nightly. Product list and detail pages render. No cart yet.

**Estimated time:** 10-14 hours

## Sprint 2 deliverables

1. `Product`, `Variant`, `ProductImage` models with full Printify field mapping
2. `printify_client.py` service module with all needed API methods
3. Management command `sync_printify_products` that pulls products for a given brand
4. Heroku Scheduler job runs sync nightly at 03:00 UTC
5. Product list view at `/shop/` showing all active products for the current brand
6. Product detail view at `/shop/<slug>/` with variant selector
7. Out-of-stock variants hidden or grayed out
8. Size guide rendered from Printify size data
9. Webhook endpoint stub for Printify (will be wired in Sprint 4)
10. Admin shows Products and Variants, read-only since they sync from Printify

## Sprint 2 implementation notes

### 2.1 Printify API basics

Base URL: `https://api.printify.com/v1/`
Auth: `Authorization: Bearer <PERSONAL_ACCESS_TOKEN>`

Key endpoints:
- `GET /shops.json` — list shops
- `GET /shops/{shop_id}/products.json?limit=50&page=1` — paginated product list
- `GET /shops/{shop_id}/products/{product_id}.json` — product detail with variants
- `POST /shops/{shop_id}/orders.json` — submit order
- `GET /shops/{shop_id}/orders/{order_id}.json` — order detail
- `POST /shops/{shop_id}/orders/shipping.json` — get shipping rates

Rate limits: 600 req/min, 200 req/30s on catalog endpoints. Build retry-with-backoff into the client.

### 2.2 Product model

```python
class Product(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="products")
    printify_product_id = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300, unique=True)
    description = models.TextField()
    blueprint_id = models.IntegerField()  # Printify blueprint (e.g., "Unisex Heavy Cotton Tee")
    print_provider_id = models.IntegerField()
    tags = models.JSONField(default=list)
    is_published = models.BooleanField(default=True)
    base_retail_price_cents = models.IntegerField()  # set in Printify mockup pricing
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_synced_at = models.DateTimeField(null=True)

class Variant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    printify_variant_id = models.IntegerField()
    sku = models.CharField(max_length=100)
    title = models.CharField(max_length=200)  # "M / Black"
    size = models.CharField(max_length=20)
    color = models.CharField(max_length=50)
    price_cents = models.IntegerField()
    cost_cents = models.IntegerField()  # what Printify charges you
    is_available = models.BooleanField(default=True)
    is_enabled = models.BooleanField(default=True)

class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    url = models.URLField(max_length=500)
    is_default = models.BooleanField(default=False)
    position = models.IntegerField(default=0)
    variant_ids = models.JSONField(default=list)  # which variants this image represents
```

### 2.3 Printify client

```python
# catalog/printify_client.py
import requests
from django.conf import settings
from typing import Optional
import time

class PrintifyClient:
    BASE_URL = "https://api.printify.com/v1"

    def __init__(self, access_token: Optional[str] = None):
        self.token = access_token or settings.PRINTIFY_ACCESS_TOKEN
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "EastGoshenApparel/1.0",
        })

    def _request(self, method, path, **kwargs):
        url = f"{self.BASE_URL}{path}"
        for attempt in range(3):
            r = self.session.request(method, url, timeout=30, **kwargs)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    def list_products(self, shop_id, page=1, limit=50):
        return self._request("GET", f"/shops/{shop_id}/products.json",
                             params={"page": page, "limit": limit})

    def get_product(self, shop_id, product_id):
        return self._request("GET", f"/shops/{shop_id}/products/{product_id}.json")

    def calculate_shipping(self, shop_id, address, line_items):
        payload = {"address_to": address, "line_items": line_items}
        return self._request("POST", f"/shops/{shop_id}/orders/shipping.json", json=payload)

    def create_order(self, shop_id, payload):
        return self._request("POST", f"/shops/{shop_id}/orders.json", json=payload)

    def get_order(self, shop_id, order_id):
        return self._request("GET", f"/shops/{shop_id}/orders/{order_id}.json")
```

### 2.4 Sync command

```python
# catalog/management/commands/sync_printify_products.py
class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--brand", required=True, help="Brand domain")

    def handle(self, *args, **options):
        brand = Brand.objects.get(domain=options["brand"])
        client = PrintifyClient()
        page = 1
        while True:
            resp = client.list_products(brand.printify_shop_id, page=page)
            for p in resp["data"]:
                self.sync_product(brand, p, client)
            if not resp.get("next_page_url"):
                break
            page += 1
```

The sync function should upsert Product + Variants + Images in a transaction, and mark variants no longer returned by Printify as `is_enabled=False` rather than deleting them (preserves order history references).

### 2.5 Heroku Scheduler

```bash
heroku addons:open scheduler
# Add job: python manage.py sync_printify_products --brand=chesco.io
# Frequency: Daily at 03:00 UTC
```

## Sprint 2 acceptance criteria

- [ ] Running sync command pulls all Printify products into local DB
- [ ] Product list page shows products with images, titles, prices
- [ ] Product detail page renders variants with size/color picker
- [ ] Out-of-stock variants are visually disabled
- [ ] Size guide displays correctly
- [ ] Scheduler runs nightly without errors (verify via Heroku logs after first run)

## Sprint 2 — delivery notes (deviations from plan as written)

Documented at the end of Sprint 2 so the plan stays the source of truth for Sprints 3-5.

- **`Product.slug` is per-brand unique, not globally unique.** Plan said `slug = SlugField(unique=True)`; shipped with `unique_together = [('brand', 'slug')]`. Global uniqueness would have broken the multi-brand promise — brand #2 couldn't ship a design called "chesco-tee" if brand #1 already had one. `BrandMiddleware` already scopes per-brand lookups, so per-brand uniqueness is sufficient. The product detail view does `Product.objects.get(brand=request.brand, slug=slug)`.
- **`Variant` has `unique_together = [('product', 'printify_variant_id')]`.** Not in the plan as written, but without it a partially-failed re-sync could insert duplicate variant rows. The sync command uses `update_or_create` on this pair as the natural key.
- **`WebhookEvent` carries a `source` field; uniqueness is on `(source, event_id)`.** Plan implied just `event_id`. Stripe and Printify both deliver events with their own `id` namespace and could theoretically collide; per-source uniqueness costs nothing and removes the ambiguity. `source` is also a useful filter in admin.
- **`WebhookEvent` lives in `orders/models.py`, the webhook view lives in `orders/views.py`.** Plan put `WebhookEvent` in the models inventory at the top without specifying an app; `orders` was the obvious home since both the Stripe webhook (Sprint 3) and Printify webhook (Sprint 4 wiring) act on orders. Keeps webhook handling in one app.
- **Size guide ships as "available sizes" only, not measurement tables.** Plan called for measurements pulled from "Printify's blueprint data." The per-product API response gives size *labels* but not chest/length measurements. Pulling real measurements requires `GET /v1/catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/variants.json` and per-blueprint schema mapping (different garments measure differently — tee vs. hoodie vs. hat). The customer-facing benefit at launch is marginal — Printify's mockup pages already include sizing — so v1 ships a clean partial that lists available sizes plus a "email us for specific measurements" line. Real measurement tables are a 2.0 item.
- **Added a `cents` template filter.** `catalog/templatetags/catalog_extras.py` exposes `{{ price_cents|cents }}` which formats integer cents as `$X.YY` (and `—` for zero/null). Single source of truth for price formatting across list, detail, and (Sprint 3+) cart/order templates. Avoids the floatformat/slice contortions that were creeping into the templates.
- **`Variant.title` falls back to `"{size} / {color}"` when Printify doesn't supply one.** Plan implied Printify always populates it; in practice the field is sometimes empty for single-option products. Belt-and-suspenders.
- **`Product.description` is rendered with `|safe`.** Printify returns HTML descriptions. Since we control the Printify shop, the source is trusted; this is the same risk profile as the HuntScrape blog renderer. If a brand front ever shares a Printify shop with an untrusted seller this would need to change to bleach-sanitized rendering.
- **`sync_printify_products` has `--dry-run` and `--limit-pages` flags beyond the plan.** First-sync safety: `--dry-run` confirms pagination and parsing without writing; `--limit-pages` is a debugging knob for a partial sync against a large shop. Production scheduler job uses neither.
- **The sync command continues past per-product failures rather than aborting the whole run.** Each product is its own transaction; a failure on product N gets logged and the run moves to product N+1. The end-of-run summary prints `products_failed` so a recurring failure is visible without blocking the rest of the catalog from updating.
- **Product images are replaced wholesale on each sync, not diffed.** Plan didn't specify; diffing image URLs against Printify's response would save a few inserts but adds complexity. Replace-all is correct for v1 and trivially safe (ProductImage has no FK references from other tables).
- **Known edge case: products with all variants disabled still appear on `/shop/` if `is_published=True`.** They render with `display_price_cents = 0` and the empty `—` price. The clean fix is to unpublish them in Printify (which propagates via `visible=False` -> `is_published=False`). Documenting rather than coding a guard because the right action is in Printify, not in Django.
- **No Printify webhook signature verification yet.** Sprint 2 deliverable #9 was "webhook endpoint stub" and that's what shipped: parses JSON, dedupes on `(source, event_id)`, persists to `WebhookEvent`, returns 200. Sprint 4 adds HMAC verification against `settings.PRINTIFY_WEBHOOK_SECRET` (header: `X-Printify-Signature`) and dispatches to event-type handlers.
- **Operational follow-up (not in code):**
  1. In Django admin, set `Brand.printify_shop_id` for chesco.io before running sync.
  2. Set `PRINTIFY_ACCESS_TOKEN` in both `.env` (local) and Heroku config vars.
  3. After verifying a clean local sync, add the Scheduler job: `python manage.py sync_printify_products --brand=chesco.io` daily at 03:00 UTC.
  4. The Printify webhook URL to register in Printify is `https://chesco.io/webhooks/printify/`. Sprint 2 only logs events; safe to register the URL anytime, but no behavior change happens until Sprint 4.
- **Touched `chescoio/settings/local.py` to fix a Sprint 1 latent bug.** The Sprint 1 fallback used `dj_database_url.config(default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')`. On Windows the interpolated path contains backslashes (`sqlite:///C:\django\...`) that some `dj_database_url` versions fail to parse, silently returning `{}` and giving Django the dummy backend. `makemigrations` worked (no cursor needed) but `migrate` failed with "settings.DATABASES is improperly configured. Please supply the ENGINE value." Replaced with an explicit `if DATABASE_URL: dj_database_url.parse(...) else: { 'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3' }`. Production config is unchanged (still uses `dj_database_url.config()` because Heroku always sets `DATABASE_URL`).

---

# Sprint 3 — Cart & Stripe Checkout

**Goal:** Customer can add to cart, enter shipping address, see dynamic shipping rates, complete payment via Stripe Checkout with Stripe Tax enabled.

**Estimated time:** 10-14 hours

## Sprint 3 deliverables

1. `Cart` and `CartItem` models, session-keyed
2. Add-to-cart, update-quantity, remove-from-cart endpoints (HTMX-driven)
3. Mini cart header that updates via HTMX swap
4. Cart page at `/cart/` with full line items, subtotal
5. Checkout flow that calls Printify shipping rate API before redirect
6. Stripe Checkout session created with line items + shipping options + Stripe Tax enabled
7. Success and cancel pages
8. Webhook endpoint `/webhooks/stripe/` for `checkout.session.completed`
9. `Order` and `OrderItem` records created from Stripe webhook
10. Idempotency: `WebhookEvent` model logs every event ID, second receipt is a no-op

## Sprint 3 implementation notes

### 3.1 Cart model

Session-keyed, not user-keyed (guest checkout).

```python
class Cart(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=100, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def subtotal_cents(self):
        return sum(item.line_total_cents for item in self.items.all())

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)

    @property
    def line_total_cents(self):
        return self.variant.price_cents * self.quantity
```

Add a periodic cleanup task: delete carts older than 30 days.

### 3.2 Stripe Checkout session

```python
import stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

def create_checkout_session(request, cart):
    line_items = [{
        "price_data": {
            "currency": "usd",
            "product_data": {
                "name": item.variant.product.title,
                "description": item.variant.title,
                "images": [item.variant.product.images.filter(is_default=True).first().url],
            },
            "unit_amount": item.variant.price_cents,
            "tax_behavior": "exclusive",
        },
        "quantity": item.quantity,
    } for item in cart.items.all()]

    # Get shipping rates from Printify FIRST
    # Then pass them as shipping_options to Stripe

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        success_url=f"https://{request.brand.domain}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"https://{request.brand.domain}/cart/",
        automatic_tax={"enabled": True},
        shipping_address_collection={"allowed_countries": ["US"]},
        shipping_options=shipping_options,  # built from Printify rate API call
        metadata={
            "brand_id": str(request.brand.id),
            "cart_id": str(cart.id),
        },
    )
    return session
```

### 3.3 The shipping rate dance

Stripe Checkout supports shipping rate configuration but not real-time rate calculation per address. Options:

**Option A (simpler, v1):** Calculate shipping at the cart page, before redirect to Stripe. Customer enters ZIP at cart, you call Printify shipping rate API, you pass the resulting rate(s) to Stripe as fixed `shipping_options`. Stripe shows the rate at checkout. If customer changes address at Stripe, the rate may not match perfectly, but Printify will accept the order regardless. Acceptable for v1.

**Option B (better, v2):** Use Stripe's `shipping_rates` API to register dynamic rates. More work, defer to later.

Go with Option A for v1.

### 3.4 Stripe webhook

```python
# orders/views.py
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    # Idempotency check
    if WebhookEvent.objects.filter(event_id=event["id"]).exists():
        return HttpResponse(status=200)
    WebhookEvent.objects.create(event_id=event["id"], event_type=event["type"], payload=event.to_dict())

    if event["type"] == "checkout.session.completed":
        handle_checkout_completed(event["data"]["object"])

    return HttpResponse(status=200)
```

`handle_checkout_completed` creates the local `Order` record, copies line items, captures shipping address, and triggers the Printify order submission (covered in Sprint 4).

## Sprint 3 acceptance criteria

- [ ] Can add items to cart and see them persist across page loads
- [ ] HTMX-driven cart updates work without full page reload
- [ ] Cart page shows correct subtotal
- [ ] Checkout button redirects to Stripe Checkout with correct line items
- [ ] Stripe Tax calculates correctly (PA clothing exempt confirmed in tax preview)
- [ ] Shipping rate appears at Stripe checkout
- [ ] Successful payment creates an Order record locally
- [ ] Duplicate webhook delivery does not create duplicate orders

---

# Sprint 4 — Printify Order Submission & Status Sync

**Goal:** Paid orders auto-submit to Printify. Printify webhooks update local order status. Email notifications fire on key state changes.

**Estimated time:** 8-12 hours

## Sprint 4 deliverables

1. After `checkout.session.completed`, order is auto-submitted to Printify
2. `Order.printify_order_id` is stored once Printify accepts
3. Webhook endpoint `/webhooks/printify/` configured to receive Printify events
4. Webhook handles: `order:created`, `order:sent-to-production`, `order:shipment:created`, `order:shipment:delivered`
5. Email templates (text + HTML) for: order confirmation, shipped notification with tracking
6. django-mailer queues emails; release-phase or scheduled worker drains queue
7. Admin shows order status, Printify order ID, tracking number, can manually retry failed submissions
8. Failure handling: if Printify rejects the order (invalid address, out of stock), mark order as `submission_failed` and send admin alert email

## Sprint 4 implementation notes

### 4.1 Order submission

```python
def submit_order_to_printify(order):
    client = PrintifyClient()
    payload = {
        "external_id": str(order.id),
        "label": f"chesco-{order.id}",
        "line_items": [
            {
                "product_id": item.variant.product.printify_product_id,
                "variant_id": item.variant.printify_variant_id,
                "quantity": item.quantity,
            }
            for item in order.items.all()
        ],
        "shipping_method": order.shipping_method_code,  # 1 = standard
        "send_shipping_notification": False,  # we send our own
        "address_to": {
            "first_name": order.first_name,
            "last_name": order.last_name,
            "email": order.email,
            "phone": order.phone or "",
            "country": "US",
            "region": order.state,
            "address1": order.address_line_1,
            "address2": order.address_line_2 or "",
            "city": order.city,
            "zip": order.postal_code,
        },
    }
    resp = client.create_order(order.brand.printify_shop_id, payload)
    order.printify_order_id = resp["id"]
    order.status = "submitted"
    order.save()
```

Wrap this in a try/except. On failure, set `order.status = "submission_failed"`, log the error, send admin alert via django-mailer.

### 4.2 Printify webhook

Configure in Printify admin: Settings → Webhooks → Add webhook pointing at `https://chesco.io/webhooks/printify/`. Subscribe to all order events.

```python
@csrf_exempt
def printify_webhook(request):
    # Printify signs webhooks with HMAC. Verify signature.
    signature = request.META.get("HTTP_X_PRINTIFY_SIGNATURE", "")
    expected = hmac.new(
        settings.PRINTIFY_WEBHOOK_SECRET.encode(),
        request.body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return HttpResponse(status=403)

    event = json.loads(request.body)
    event_id = event.get("id")
    if WebhookEvent.objects.filter(event_id=event_id).exists():
        return HttpResponse(status=200)
    WebhookEvent.objects.create(event_id=event_id, event_type=event["type"], payload=event)

    handler_map = {
        "order:sent-to-production": handle_order_in_production,
        "order:shipment:created": handle_order_shipped,
        "order:shipment:delivered": handle_order_delivered,
    }
    handler = handler_map.get(event["type"])
    if handler:
        handler(event["resource"])
    return HttpResponse(status=200)
```

### 4.3 Email templates

Three templates needed for v1:
1. `order_confirmation.txt` / `.html` — fires on `checkout.session.completed`
2. `order_shipped.txt` / `.html` — fires on `order:shipment:created`, includes tracking number and URL
3. `admin_order_failed.txt` — internal alert for submission failures

Mirror the django-mailer pattern from HuntScrape: send via `mail.send()`, drain queue via Heroku Scheduler running `send_mail` and `retry_deferred` every 15 minutes.

## Sprint 4 acceptance criteria

- [ ] Test order completes Stripe checkout → Printify order submitted within 30 seconds
- [ ] Order confirmation email arrives in customer inbox
- [ ] When Printify status changes, local order status updates within seconds of webhook
- [ ] Shipped notification email contains valid tracking URL
- [ ] Forcing a Printify webhook replay does not duplicate state changes
- [ ] Failed submission triggers admin alert email

---

# Sprint 5 — Polish, Legal, SEO & Launch

**Goal:** Public-facing polish, all legal pages, SEO basics, launch announcements, first real order placed by you to validate end-to-end.

**Estimated time:** 8-12 hours

## Sprint 5 deliverables

1. Privacy policy, terms of service, returns policy pages (forked from HuntScrape patterns, adapted for apparel)
2. Size guide page (could be per-product or general)
3. About / Story page (brand voice, who you are, why chesco)
4. Contact page with form that emails `support_email`
5. SEO meta tags per page: title, description, OpenGraph image, Twitter card
6. Per-product OG image set to default product image
7. `robots.txt` and dynamically generated `sitemap.xml`
8. Email signup form in footer, posts to `EmailSignup` model
9. Order lookup page at `/orders/lookup/` (email + order ID)
10. 404 and 500 pages branded
11. End-to-end test order placed and received
12. Cloudflare WAF rules applied (mirror HuntScrape pattern)
13. Launch checklist completed

## Sprint 5 implementation notes

### 5.1 Critical copy to write (yourself, not Claude — brand voice matters)

- Privacy policy: cover Stripe data handling, Printify data handling, Plausible analytics, Meta Pixel, email signups
- Terms of service: arbitration clause, governing law (PA), final sale policy for POD items
- Returns policy: defects only, 14-day window, no returns for sizing
- Size guide: pull measurements from Printify, format as clear table

### 5.2 SEO setup

```python
# In base template
<meta property="og:title" content="{% block og_title %}{{ request.brand.name }}{% endblock %}">
<meta property="og:description" content="{% block og_description %}{{ request.brand.tagline }}{% endblock %}">
<meta property="og:image" content="{% block og_image %}{{ request.brand.logo_url }}{% endblock %}">
<meta property="og:url" content="https://{{ request.brand.domain }}{{ request.path }}">
<meta name="twitter:card" content="summary_large_image">
```

Override `og_image` per product detail page to use the default product image.

### 5.3 Order lookup

Simple form: email + order ID → if match, show order detail page with current status, line items, tracking link. No auth required (the order ID itself is the secret).

### 5.4 Launch checklist (run through this manually)

- [ ] All env vars set in Heroku production
- [ ] Stripe in live mode (not test)
- [ ] Stripe webhook endpoint registered with live signing secret
- [ ] Printify shop confirmed connected to live store
- [ ] Printify webhook registered
- [ ] Stripe Tax registered for PA
- [ ] DNS propagated, SSL valid
- [ ] Plausible tracking confirmed firing
- [ ] Meta Pixel firing on key events (ViewContent, AddToCart, Purchase)
- [ ] Email sending works (django-mailer queue draining)
- [ ] Order confirmation email DKIM/SPF passing (check via mail-tester.com)
- [ ] Cloudflare WAF rules active
- [ ] Backup verified: `heroku pg:backups:capture` runs clean
- [ ] First real order placed by you, fulfilled by Printify, received in mail
- [ ] Refund flow tested (manually issue a refund via Stripe, verify Order updates)

---

# Post-launch / 2.0 list

Things deliberately deferred from v1, documented here so they don't get forgotten:

- Real product photography (lifestyle shots at Longwood, French Creek, local breweries)
- Etsy storefront pointing at same Printify shop (separate sales channel)
- Abandoned cart recovery emails (Stripe Checkout supports natively — turn on in dashboard)
- Email marketing integration (Buttondown or Mailchimp for the signup list)
- Discount codes / coupon system (Stripe supports natively — surface at checkout)
- Bundle deals ("buy 2 get 1 free")
- Reviews / testimonials on product pages
- Wishlist / favorites (requires accounts — defer indefinitely or use localStorage)
- B2B custom order intake form (the actual revenue lane — high priority for 2.0)
- Second brand front launched on same backend (validates multi-brand architecture)
- Real-time shipping rate calculation via Stripe shipping_rates API
- Google Shopping feed generation
- Structured product data (JSON-LD) for Google
- A/B testing framework on pricing

---

# Reusable code patterns from existing projects

Pull from these directly, do not rewrite:

- **HuntScrape** (`C:\django\prod-django\culltrack\`): Tenant middleware → adapt to Brand middleware. django-mailer setup. Stripe webhook handling. Meta Pixel integration. Cloudflare WAF rules. SSL redirect fix.
- **Apeirum** (`C:\django\prod-django\myticker\`): Daily Heroku Scheduler patterns. WebhookEvent idempotency pattern. Retry-with-backoff for external API calls.
- **Honey & Pine** (`C:\django\prod-django\honeyandpine\`): Tailwind CDN approach (no local build). Plausible integration. Form handling patterns.
- **East Goshen** (`C:\django\prod-django\eastgoshen\`): Canonical domain middleware. Project metadata patterns.

---

# Operating rules (for every sprint)

1. **Stage before production.** ~~Every sprint ends with a deploy to a staging Heroku app first, then promotes to production.~~ **Superseded as of Sprint 1**: dev → prod direct. Revisit if chesco grows enough users that the cost of a broken deploy exceeds the cost of running a staging dyno.
2. **No raw secrets in code.** Everything via environment variables.
3. **Migrations are reviewed before deploy.** Especially destructive ones.
4. **Test orders are placed in test mode first.** Never use the live Stripe key for end-to-end testing until Sprint 5 acceptance.
5. **One PR per sprint.** Reviewed against the sprint acceptance criteria before merge.
6. **Document every external integration's credentials** in a private secrets vault (1Password, Bitwarden, whatever you already use). Future-you will thank present-you.

---

# Final notes

This plan is opinionated by design. The architecture decisions are locked because deferring them creates rework. The sprint boundaries are sized so each one is a single weekend of focused work. Acceptance criteria are explicit so you (or a future session) can verify completion without ambiguity.

The biggest risk to this plan is scope creep — wanting to add Sprint 1.5 features ("just one more thing before products go in"). Resist this. Ship the boring scaffolding first, ship the boring integration second, ship the boring checkout third. The fun parts (designs, brand voice, marketing) come after the platform works.

If anything in this plan needs to change based on something discovered during the build, update this document rather than letting the implementation drift from the plan. The plan is the source of truth.
