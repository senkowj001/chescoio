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
- Heroku Scheduler for hourly Printify product sync (with `product:publish:*` webhook handlers added in Sprint 4 for near-instant publish-to-live latency)

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

**Goal:** Products sync from Printify to local DB hourly, with an admin-triggered "Sync Now" action available as an operational override. Product list and detail pages render. No cart yet.

**Estimated time:** 10-14 hours

## Sprint 2 deliverables

1. `Product`, `Variant`, `ProductImage` models with full Printify field mapping
2. `printify_client.py` service module with all needed API methods
3. Management command `sync_printify_products` that pulls products for a given brand
4. Heroku Scheduler job runs sync hourly
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
# Frequency: Hourly
```

Heroku Scheduler's three frequency options are every 10 minutes, hourly, or daily. Hourly is the right balance here: the catalog changes rarely, the polling interval is the safety net rather than the primary path (product-publish webhooks added in Sprint 4 cover the "new t-shirt published" case), and the admin "Sync Now" action (Sprint 3) handles operator-driven refreshes between scheduled runs.

## Sprint 2 acceptance criteria

- [ ] Running sync command pulls all Printify products into local DB
- [ ] Product list page shows products with images, titles, prices
- [ ] Product detail page renders variants with size/color picker
- [ ] Out-of-stock variants are visually disabled
- [ ] Size guide displays correctly
- [ ] Scheduler runs hourly without errors (verify via Heroku logs after first run)

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
  3. After verifying a clean local sync, add the Scheduler job: `python manage.py sync_printify_products --brand=chesco.io` hourly.
  4. The Printify webhook URL to register in Printify is `https://chesco.io/webhooks/printify/`. Sprint 2 only logs events; safe to register the URL anytime, but no behavior change happens until Sprint 4.
- **Touched `chescoio/settings/local.py` to fix a Sprint 1 latent bug.** The Sprint 1 fallback used `dj_database_url.config(default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')`. On Windows the interpolated path contains backslashes (`sqlite:///C:\django\...`) that some `dj_database_url` versions fail to parse, silently returning `{}` and giving Django the dummy backend. `makemigrations` worked (no cursor needed) but `migrate` failed with "settings.DATABASES is improperly configured. Please supply the ENGINE value." Replaced with an explicit `if DATABASE_URL: dj_database_url.parse(...) else: { 'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3' }`. Production config is unchanged (still uses `dj_database_url.config()` because Heroku always sets `DATABASE_URL`).
- **Touched `chescoio/settings/local.py` again to fix the `load_dotenv` ordering.** Sprint 1's `local.py` ran `from .base import *` *before* `load_dotenv(.env)`. That worked as long as `base.py` didn't read any env vars at module-import time (the only env-driven thing was `DATABASE_URL`, which is read down in `local.py` itself, *after* `load_dotenv`). Sprint 2 added `PRINTIFY_ACCESS_TOKEN = os.environ.get(...)` to `base.py`, and that read happened during the `from .base import *` line — before `load_dotenv` populated `os.environ` — so the setting froze to `''` even with the token present in `.env`. Fixed by hoisting `load_dotenv` above the base import, with a small local `_PROJECT_ROOT` since `BASE_DIR` isn't defined yet at that point. Lesson for future sprints: any env var read in `base.py` requires `load_dotenv` to run first in dev. Production is unaffected (Heroku sets env vars directly, no `.env`).

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
11. Admin "Sync Now" action on the Brand model in Django admin — triggers `sync_printify_products` for the selected brand synchronously, surfaces success/failure with a count of products synced

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

Add a periodic cleanup task: delete carts older than 7 days. (Matches the canonical models inventory at the top of this plan. Note: Django's default `SESSION_COOKIE_AGE` is 14 days, so a returning visitor between day 7 and day 14 may have an intact session with an empty cart — that's the desired behavior; stale carts should be pruned.)

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

    # Idempotency check — uniqueness is on (source, event_id), so both fields
    # are required. Without source, a Stripe event would collide with any
    # Printify event whose id happens to match.
    if WebhookEvent.objects.filter(
        source=WebhookEvent.SOURCE_STRIPE,
        event_id=event["id"],
    ).exists():
        return HttpResponse(status=200)
    WebhookEvent.objects.create(
        source=WebhookEvent.SOURCE_STRIPE,
        event_id=event["id"],
        event_type=event["type"],
        payload=event.to_dict(),
    )

    if event["type"] == "checkout.session.completed":
        handle_checkout_completed(event["data"]["object"])

    return HttpResponse(status=200)
```

`handle_checkout_completed` creates the local `Order` record, copies line items, captures shipping address, and triggers the Printify order submission (covered in Sprint 4).

### 3.5 Admin "Sync Now" action

Add a Django admin action on the `Brand` model in `brands/admin.py` (or wherever Brand is registered). Implementation pattern:

```python
from django.contrib import admin, messages
from django.core.management import call_command
from io import StringIO

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    actions = ["sync_printify_products_now"]

    @admin.action(description="Sync Printify products now")
    def sync_printify_products_now(self, request, queryset):
        for brand in queryset:
            if not brand.printify_shop_id:
                self.message_user(
                    request,
                    f"{brand.name}: skipped (no printify_shop_id set).",
                    level=messages.WARNING,
                )
                continue
            out = StringIO()
            try:
                call_command(
                    "sync_printify_products",
                    brand=brand.domain,
                    stdout=out,
                )
                self.message_user(
                    request,
                    f"{brand.name}: {out.getvalue().strip().splitlines()[-1]}",
                    level=messages.SUCCESS,
                )
            except Exception as exc:
                self.message_user(
                    request,
                    f"{brand.name}: sync failed — {exc}",
                    level=messages.ERROR,
                )
```

Notes:
- Synchronous execution is fine at the current product volume (<50 products → ~10–15s, well under Heroku's 30s request timeout). When the catalog grows past ~100 products, revisit with a background job (Celery / RQ / `django-q2`); flag this in delivery notes if scale considerations come up earlier.
- Concurrency with the hourly Scheduler run is safe — `update_or_create` semantics in the sync command tolerate overlap. Worst case is a few redundant API calls and writes; no corruption.
- Don't add a lock or a "sync already in progress" guard for v1. Premature complexity.
- The admin message takes the last line of the management command's stdout, which is the end-of-run summary line (products_synced / products_failed). If that line format changes in the sync command later, adjust here too.

## Sprint 3 acceptance criteria

- [ ] Can add items to cart and see them persist across page loads
- [ ] HTMX-driven cart updates work without full page reload
- [ ] Cart page shows correct subtotal
- [ ] Checkout button redirects to Stripe Checkout with correct line items
- [ ] Stripe Tax calculates correctly (PA clothing exempt confirmed in tax preview)
- [ ] Shipping rate appears at Stripe checkout
- [ ] Successful payment creates an Order record locally
- [ ] Duplicate webhook delivery does not create duplicate orders
- [ ] Admin "Sync Now" action on a Brand runs `sync_printify_products` synchronously and surfaces success / failure / product count in the admin message frame

## Sprint 3 — delivery notes (deviations from plan as written)

Documented at the end of Sprint 3 so the plan stays the source of truth for Sprints 4-5.

- **Sprint 3 is deployed and validated in production, not just locally.** End-to-end checkout works on `https://www.chesco.io`: cart → Stripe Checkout → webhook → Order created. Idempotency verified by resending an event from the Stripe dashboard (no duplicate Order created). PA clothing tax exemption verified ($0.00 tax on a new order after the tax-code correction below). Custom domain, ACM SSL, and DNS all live.
- **The whole Stripe test-mode dev loop was more painful than the sprint plan implied.** A partial log of the traps we walked into, in the order they appeared: (a) no Stripe MCP available in claude.ai web chat surface, so Claude can't set the account up directly — workaround was writing `scripts/configure_stripe_dev.py` which does head office, PA registration, and default tax code via the `stripe` Python library; (b) `stripe.tax.Registration.create` refuses to run until `stripe.tax.Settings` has a head office address set (had to add step 2 to the script); (c) `stripe.checkout.Session.create` with `automatic_tax=True` refuses to run without a default `tax_code` in tax settings OR a `tax_code` on every line item (added step 3); (d) the dynamic clothing-code lookup in that script initially picked `txcd_30011201 Fur Clothing` because the shortest-name heuristic prefers alphabetically-early matches and "Fur Clothing" beat "Clothing & Footwear" — fur is one of PA's explicit clothing-exemption exceptions, so the tax exemption never fired. Fix: added a `--force-code=txcd_XXXXXXX` argument to the script, then explicitly set `txcd_30011000 Clothing & Footwear` as the default. **Lesson for future scripts**: for tax code selection specifically, don't heuristic-pick; hardcode `txcd_30011000` for apparel businesses.
- **Stripe CLI account-coupling is a real footgun.** `stripe login` binds the CLI to whichever Stripe account the user selects in the browser. `stripe listen` then forwards events for *that* account. But `STRIPE_SECRET_KEY` in `.env` is a separate authentication chain — if it's for a different account, `stripe listen` forwards synthetic-trigger events (fired by the CLI itself) but not real checkout events (fired by Stripe against the `.env` key's account). Symptom: synthetic triggers work in dev, real checkouts hang forever on the polling page with no webhook ever arriving. Diagnosis was slow because both surfaces look identical. **Sidesteps in production**: dashboard-registered webhook endpoints are unambiguously bound to a single account, so the CLI plays no role. We effectively skipped local end-to-end validation and went straight to deployed test-mode. That worked and unblocked the sprint.
- **`checkout.session.completed` handler is defensive against sessions we didn't create.** Synthetic `stripe trigger` events and any external session (e.g. if the webhook URL is ever re-registered or shared) arrive without our `metadata.brand_id / cart_id`. Rather than raise (which triggers Stripe's exponential-backoff retry, creating a persistent 500 storm in the log), the handler now soft-skips with a `WARNING ... not ours, skipping order creation` log line and returns 200. Only sessions with our metadata are processed. See `orders/checkout_services.py::create_order_from_stripe_session`.
- **`STRIPE_HANDLED_EVENT_TYPES` frozenset in `orders/views.py::stripe_webhook`.** Stripe fires 7+ events per completed checkout (`product.created`, `price.created`, `charge.succeeded`, `payment_intent.created`, `payment_intent.succeeded`, `checkout.session.completed`, `charge.updated`). Our handler cares about exactly one of them. The rest now short-circuit to a 200 without touching the DB, without allocating a `WebhookEvent` audit row, and without any risk of a serialization edge case on a payload shape we never look at causing a 500 that Stripe would then retry. Extend the frozenset when future sprints add handlers for other event types.
- **Checkout success page bounds polling.** The plan's implicit design was "poll indefinitely until the Order materializes." First real test spun for 30 minutes because the webhook wasn't landing (stale CLI). Now capped at `CHECKOUT_SUCCESS_MAX_POLLS = 15` (15 attempts × 2s = 30s budget). After the budget expires, the customer sees a "payment received, we're still finalizing your receipt" state with a "Check again" button, not an infinite spinner. Server-side `attempt` counter carried in the URL query string so the budget survives the HTMX outerHTML swap. See `orders/views.py::checkout_success` and `templates/orders/_checkout_success_status.html`.
- **`ForceWwwRedirectMiddleware` added.** Canonicalizes apex-domain traffic (`chesco.io`) to the www subdomain in a single 301 hop. Runs first in the middleware chain — before `SecurityMiddleware` — so `http://chesco.io/foo` collapses to `https://www.chesco.io/foo` in one 301 instead of chaining through the SSL-redirect middleware for an extra hop. Driven by `settings.FORCE_WWW_DOMAINS`; no-op in dev because `local.py` doesn't set it. Production sets `FORCE_WWW_DOMAINS = ['chesco.io']`. Extend when adding future brand domains that should www-canonicalize. See `brands/middleware.py::ForceWwwRedirectMiddleware`.
- **Django's `{# ... #}` comment syntax is single-line only, and multi-line variants leak into the rendered page as visible text.** This trap bit us three separate times in Sprint 3 (base.html, checkout success template, homepage). **Rule going forward**: use `{% comment %}...{% endcomment %}` for any comment that spans lines. `{# ... #}` is only for comments that fit on one line.
- **OOB swap pattern discovered.** A partial reused as both a primary swap target AND an out-of-band swap target needs the `hx-swap-oob` attribute set conditionally via context flag, not hardcoded. Otherwise HTMX strips the OOB element from the response before the primary swap, leaving the primary swap with empty content. `_mini_cart.html` now takes an `as_oob` template variable; cart_add renders without it (mini-cart is the primary target), cart_update/cart_remove render with `as_oob=True` (mini-cart is an OOB update alongside a `#cart-contents` primary swap). Similarly, `_cart_contents.html` conditionally includes the OOB mini-cart only when the view sets `include_oob_minicart=True` (i.e. only on HTMX responses), so the full-page cart render doesn't emit duplicate `id="mini-cart"` elements.
- **Tailwind v4 in-browser JIT emits `@theme` variables but they aren't reliably available to arbitrary `<style>` blocks on the same page.** Symptom was an invisible "Add to cart" button (white text on transparent background) once a variant was selected. Fixed by (a) adding a plain `:root { --color-brand-primary: ...; --color-brand-accent: ...; }` block in `base.html` alongside the existing `@theme` block so the variables are defined as raw CSS custom properties independent of Tailwind's JIT, and (b) adding hex-literal fallbacks in `var()` calls: `background-color: var(--color-brand-primary, #1a4d2e);`. **Rule going forward**: any inline `<style>` block that uses `var(--color-brand-*)` should include a hex fallback.
- **Homepage heading is charcoal (`text-neutral-900`), not brand-primary.** Design decision that fell out of debugging: using the dark green for the H1 made the page monochromatic and killed the visual pop of the (green) shop button and (amber) accent hairline. Charcoal H1 + green accent button + amber hairline reads as an intentional design system with brand colors as accents rather than dominant. Also added `text-balance max-w-md mx-auto` on the H1 so "Chester County Apparel Co." wraps as "Chester County" / "Apparel Co." instead of orphaning "Co." on its own line. `text-balance` is a Tailwind v4 utility (`text-wrap: balance`); modern browsers only, degrades gracefully to normal CSS wrap on older ones.
- **`printify_shop_id` baked into the seed migration.** Sprint 1's seed migration created the Brand row without `printify_shop_id`, so every fresh install (staging spin-up, disaster recovery restore, new dev laptop) needed an admin step before `sync_printify_products` would run. Since shop IDs are operational not secret — anyone with the Printify PAT can list them via the API — committing the value is safe. Migration edit doesn't retroactively update already-migrated databases; we set the value on prod separately via a one-line `Brand.objects.filter(...).update(...)` call through `heroku run`. Future spin-ups get it for free.
- **`configure_stripe_dev.py` grew a `--force-code` flag mid-sprint.** Originally idempotent — if a default tax code was already set, leave it. That was wrong when the initial dynamic pick was wrong (see fur-clothing story above). Now: always prints current defaults, always lists clothing candidates for diagnostic value, and supports `--force-code=txcd_XXXXXXX` to overwrite a bad pick.
- **`clear_old_carts` management command shipped.** Sprint plan deliverable at 3.1 tail-end ("Add a periodic cleanup task"). Lives at `orders/management/commands/clear_old_carts.py`. Reads `CART_EXPIRY_DAYS` from settings (default 7), supports `--dry-run` and `--days=N` for manual runs. Scheduler wiring is a Sprint 5 launch checklist item, not a Sprint 3 code item.
- **Production database `conn_max_age` lowered from 600 to 60.** Django's default 10-minute connection persistence was long enough for Heroku Postgres's idle-connection reaper to silently kill the socket before Django's next use. On a low-traffic pre-launch site, this caused a stale-socket 500 with a 15-second `psycopg2.OperationalError: connection ... failed: timeout expired`. `CONN_HEALTH_CHECKS = True` was already set, but the check happens at connection *checkout* from the pool, not on every query, so the first request after a reap could still take the dead socket. Lowering to 60s TTL makes reap collisions vanishingly rare and preserves the reconnection-cost savings for bursty traffic. See `chescoio/settings/production.py`. This is a hardening, not a bug fix — the health-check retry logic would have handled it eventually but slowly.
- **Order confirmation email deferred to Sprint 4.** `_checkout_success_status.html` currently displays "A confirmation will arrive at {{ order.email }} shortly" but nothing actually sends that email yet. Sprint 4 deliverable #7 covers the templates and django-mailer wiring. Known-lie in the copy until then; acceptable for a pre-launch site with no real customers.
- **The `configure_stripe_dev.py` filename is technically wrong now.** It runs against test mode, which is the correct scope for what it does, but it also configures things that persist across dev and production (head office, PA registration, default tax code) because production uses the same Stripe account in test mode. Rename to `configure_stripe_testmode.py` is a nice-to-have when Sprint 5 introduces the live-mode variant. Not urgent.
- **Cart page cart-cleanup edge case:** if a customer completes checkout via Stripe Link (saved payment info) on chesco.io the first time, we've seen Link's SMS verification hang in a "no code will be sent" test-mode state. Workaround for future testing: use `+` email suffixes (`user+test1@example.com`, etc.) to avoid triggering Link, or click "Pay without Link" on the checkout page. Not a code fix, just a testing note.
- **Operational follow-up (not in code, must be done before Sprint 4 starts):**
  1. Rotate the test-mode Stripe keys (`sk_test_...`, `pk_test_...`) that were pasted into chat during dev. Stripe Dashboard → Developers → API keys → Roll. Update both `.env` and `heroku config:set` with the fresh values.
  2. Rotate the Printify PAT (been on the pending list since Sprint 1). Printify → Connections → regenerate. Update `.env` and Heroku.
  3. Delete Order #1 in production admin — it was a test transaction created before the tax-code correction, and its `$1.98` tax value makes it a misleading demo artifact. Optional.
  4. Commit and push everything to GitHub `main`. Sprint 3 body of work, `ForceWwwRedirectMiddleware`, seed migration edit, checkout timeout, webhook filter, tax-code fix, `clear_old_carts`, `conn_max_age` fix, this document.

---

# Sprint 4 — Printify Order Submission, Status Sync & Product Webhooks

**Goal:** Paid orders auto-submit to Printify. Printify webhooks update local order status. Product-publish webhooks make new t-shirts appear on chesco.io within seconds of clicking Publish in Printify. Email notifications fire on key state changes.

**Estimated time:** 10-14 hours

## Sprint 4 deliverables

1. After `checkout.session.completed`, order is auto-submitted to Printify
2. `Order.printify_order_id` is stored once Printify accepts
3. Webhook endpoint `/webhooks/printify/` configured to receive Printify events
4. Webhook handles order events: `order:created`, `order:sent-to-production`, `order:shipment:created`, `order:shipment:delivered`
5. Webhook handles product events: `product:publish:started`, `product:publish:succeeded`, `product:deleted`
6. On `product:publish:started`, fetch the product detail from Printify, upsert locally (reusing the Sprint 2 sync code path for a single product), then call Printify's "Publish succeeded" endpoint to unlock the product card in the Printify UI. On sync failure, call "Publish failed" instead.
7. Email templates (text + HTML) for: order confirmation, shipped notification with tracking
8. django-mailer queues emails; release-phase or scheduled worker drains queue
9. Admin shows order status, Printify order ID, tracking number, can manually retry failed submissions
10. Failure handling: if Printify rejects the order (invalid address, out of stock), mark order as `submission_failed` and send admin alert email
11. Webhook registration command: a Django management command (`register_printify_webhooks --brand=chesco.io`) that POSTs all required webhook subscriptions (order events + product events) to Printify's `/shops/{shop_id}/webhooks.json` endpoint, idempotently. Re-running it should reconcile (update existing, create missing, leave correct ones alone).

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

Webhooks are registered programmatically via `POST /v1/shops/{shop_id}/webhooks.json`
(no Printify dashboard UI for this). Body includes the `topic`, target `url`, and a
`secret` *we generate and pass in*. Printify echoes that secret back in the HMAC on
every delivery; verify in our handler.

Registration is a one-off; write it as a small management command or do it from a
Django shell. Then subscribe to all order events.

```python
@csrf_exempt
def printify_webhook(request):
    # Printify signs webhooks with HMAC-SHA256. Header is X-Pfy-Signature,
    # format "sha256={hexdigest}".
    signature_header = request.META.get("HTTP_X_PFY_SIGNATURE", "")
    expected = "sha256=" + hmac.new(
        settings.PRINTIFY_WEBHOOK_SECRET.encode(),
        request.body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature_header, expected):
        return HttpResponse(status=403)

    event = json.loads(request.body)
    event_id = event.get("id")
    # Source-scoped idempotency (see Sprint 2 delivery notes for the source
    # field rationale on WebhookEvent).
    if WebhookEvent.objects.filter(
        source=WebhookEvent.SOURCE_PRINTIFY,
        event_id=event_id,
    ).exists():
        return HttpResponse(status=200)
    WebhookEvent.objects.create(
        source=WebhookEvent.SOURCE_PRINTIFY,
        event_id=event_id,
        event_type=event["type"],
        payload=event,
    )

    handler_map = {
        # Order events
        "order:sent-to-production": handle_order_in_production,
        "order:shipment:created": handle_order_shipped,
        "order:shipment:delivered": handle_order_delivered,
        # Product events
        "product:publish:started": handle_product_publish_started,
        "product:publish:succeeded": handle_product_publish_succeeded,
        "product:deleted": handle_product_deleted,
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

### 4.4 Product publish webhook flow

Printify's "Publish" button on a product card in the Printify UI works specially for custom / API-only stores. When clicked:

1. Printify **locks the product card** in their UI (so the merchant can't double-click).
2. Printify fires `product:publish:started` to our webhook.
3. We are expected to **do the work to make the product live on our store**, then **tell Printify** whether we succeeded or failed.
4. Printify will then unlock the card in their UI based on our response.

The relevant Printify endpoints:
- `POST /v1/shops/{shop_id}/products/{product_id}/publishing_succeeded.json`
- `POST /v1/shops/{shop_id}/products/{product_id}/publishing_failed.json` — payload: `{"reason": "..."}`

Add these methods to `PrintifyClient` in Sprint 4 (they weren't needed in Sprint 2).

The handler:

```python
def handle_product_publish_started(resource):
    """Sync this single product from Printify, then call publishing_succeeded."""
    shop_id = resource["shop_id"]
    product_id = resource["id"]  # printify product id
    brand = Brand.objects.get(printify_shop_id=shop_id)
    client = PrintifyClient()
    try:
        product_data = client.get_product(shop_id, product_id)
        # Reuse Sprint 2's per-product sync function (extract from the management
        # command so both the command and this handler share the same upsert logic).
        sync_single_product(brand, product_data)
        client.publishing_succeeded(shop_id, product_id)
    except Exception as exc:
        logger.exception("product:publish:started sync failed")
        client.publishing_failed(shop_id, product_id, reason=str(exc)[:200])
        raise

def handle_product_publish_succeeded(resource):
    # Logging-only — fires after we call publishing_succeeded above.
    # No state change needed; the local product is already in sync.
    pass

def handle_product_deleted(resource):
    shop_id = resource["shop_id"]
    product_id = resource["id"]
    Product.objects.filter(
        brand__printify_shop_id=shop_id,
        printify_product_id=str(product_id),
    ).update(is_published=False)
```

Refactor note for Sprint 2 code: the `sync_printify_products` management command's inner per-product upsert should be extracted into a `sync_single_product(brand, product_data)` function in `catalog/services.py` (or similar) that both the command and the webhook handler import. This is a small refactor and the right home for the logic; do it as part of Sprint 4 prep before wiring the webhook handler.

**Acknowledge synchronously, sync synchronously.** The handler returns 200 only after the sync + publishing_succeeded callback completes. For a single product that's typically 2 Printify API calls + a DB transaction — well under Printify's webhook timeout. If this becomes a problem (large catalogs, slow networks), move the sync to a background queue and acknowledge the webhook immediately, but for v1 the synchronous path is simpler and the latency is what we want anyway.

**Edge case:** a `product:publish:started` for a product whose `shop_id` we don't have a Brand for. Log a warning and 200; don't 500. This shouldn't happen if webhook registration is per-brand, but defensive.

### 4.5 Webhook registration

Printify webhooks must be registered via API — there's no dashboard UI. Build a management command `register_printify_webhooks` that:

1. Lists existing webhooks for the brand's `printify_shop_id`
2. Computes the desired set: all four `order:*` topics + three `product:*` topics, all pointing at `https://{brand.domain}/webhooks/printify/`, all using `settings.PRINTIFY_WEBHOOK_SECRET`
3. Creates missing subscriptions, updates ones with a stale URL, leaves correct ones alone
4. Optionally deletes stray subscriptions (`--prune` flag) so the command is fully idempotent

Run it once per brand at Sprint 4 deployment time. Re-run safely whenever the topic list or URL changes.

## Sprint 4 acceptance criteria

- [ ] Test order completes Stripe checkout → Printify order submitted within 30 seconds
- [ ] Order confirmation email arrives in customer inbox
- [ ] When Printify status changes, local order status updates within seconds of webhook
- [ ] Shipped notification email contains valid tracking URL
- [ ] Forcing a Printify webhook replay does not duplicate state changes
- [ ] Failed submission triggers admin alert email
- [ ] Clicking "Publish" on a new product in Printify causes it to appear on `https://chesco.io/shop/` within seconds (verified by stopwatch — should be <10s end to end)
- [ ] After successful sync, the product card in the Printify UI is unlocked (publishing_succeeded callback fired)
- [ ] Deleting a product in Printify causes it to disappear from `/shop/` on the next webhook delivery
- [ ] `register_printify_webhooks` is idempotent — re-running it produces no duplicates

## Sprint 4 — delivery notes (deviations from plan as written)

Documented at the end of Sprint 4 so the plan stays the source of truth for Sprint 5.

- **This sprint was implemented via a Claude session working directly against the filesystem (no live Printify/Stripe/email test run performed in-session).** Everything below reflects what shipped in code, plus explicit callouts on what still needs to be verified against the real Printify sandbox before this sprint is actually "done" per the plan's definition-of-done (end-to-end test order, DKIM/SPF check, timing of the publish-to-live webhook). Treat the acceptance-criteria checkboxes above as unchecked until John runs the real end-to-end pass described in the operational follow-up below.
- **`Order` already had `printify_order_id`, `submitted_at`, `shipped_at`, `delivered_at`, `tracking_number`, `tracking_url`, `tracking_carrier`, and `submission_error` fields from the Sprint 3 migration** — Sprint 3's model design anticipated Sprint 4's needs, so no new tracking-field migration was needed here. Added two *new* fields instead: `confirmation_sent_at` and `shipped_email_sent_at`, timestamp guards against double-sending a customer email (see next note).
- **Email idempotency is two-layered, matching the Sprint 2/3 `WebhookEvent (source, event_id)` pattern.** `WebhookEvent` dedup is the primary defense against a redelivered webhook re-triggering a handler. `Order.confirmation_sent_at` / `Order.shipped_email_sent_at` are a second, independent guard checked inside `orders/emails.py::send_order_confirmation` / `send_order_shipped` — so even a manual re-trigger (e.g. calling the sender directly from a shell) can't double-send. Deliberately *not* applied to `send_admin_order_failed`: if a retry also fails, the admin should hear about it again.
- **Confirmation email fires before Printify submission, not after.** The sprint plan's pseudocode implied submission-then-confirmation; shipped order is reversed. Rationale: the customer already paid by the time `_handle_checkout_completed` runs, so they should get a receipt regardless of what Printify does next. A Printify rejection becomes an operational problem (admin alert, manual resubmission) rather than something that delays or blocks the customer's confirmation. See `orders/views.py::_handle_checkout_completed`.
- **`submit_order_to_printify(order, force=False)` guards on `order.status == Order.STATUS_PAID` by default.** This is the idempotency guard for the whole submission step — if `_handle_checkout_completed` somehow runs twice for the same order (e.g. a `WebhookEvent` row created but never marked `processed_at`, so a Stripe retry re-enters the handler), the second call is a no-op instead of a duplicate Printify order. The admin "Retry Printify submission" action passes `force=True` to bypass the guard for orders already in `submission_failed`.
- **`order:created` is in the handled-events frozenset but its handler is logging-only.** The sprint plan's deliverable #4 lists `order:created` alongside the other three order events, but the plan's own webhook handler pseudocode (4.2) never actually maps it to a handler function. Since `submit_order_to_printify` already captures `printify_order_id` synchronously from the `create_order()` API response, the `order:created` webhook is Printify's own confirmation of something we already know. Handled (so it doesn't fall through to the "ignored, no audit row" path and go untracked), but takes no action beyond a log line. Flagging this explicitly since it's a place where the plan's deliverable list and implementation notes disagreed slightly.
- **`order:sent-to-production` and `order:shipment:delivered` intentionally do NOT send customer emails**, per the sprint prompt's stated default ("no customer email by default — noisy") for anything beyond confirmation and shipped. Only `order:shipment:created` triggers `send_order_shipped`. If John wants an "in production" or "delivered" email later, add it as an explicit ask — the prompt flagged this as a decision requiring confirmation, not a default.
- **Printify's shipment webhook payload shape is unconfirmed — `_handle_printify_order_shipped` is defensive on purpose.** Printify's docs describe a `shipments` array on the order resource (each with `number` / `url` / `carrier`), but this hasn't been exercised against a real Printify test order in this session (no live API calls were made while building this sprint). The handler tries `resource['shipments'][0]` first, then falls back to flat `tracking_number` / `tracking_url` / `carrier` keys directly on `resource`. **This needs verification against a real `order:shipment:created` delivery** — if Printify's actual shape differs from both guesses, tracking fields will save as empty strings rather than erroring (the code won't crash, but the shipped email will render without a tracking link). Check the `WebhookEvent.payload` JSON for the first real shipment webhook and adjust `_handle_printify_order_shipped` if the keys don't match.
- **`PrintifyClient.publishing_succeeded()` POSTs an empty JSON body (`{}`).** The sprint plan doesn't specify a request body for this endpoint beyond "POST publishing_succeeded.json". If Printify's API actually requires an `external: {id, handle}` payload (some POD platforms do, to let the merchant's storefront ID show up in their dashboard), this will need a follow-up fix once tested against the real API. Flagging now rather than guessing at an unverified schema.
- **`PrintifyClient._request` now treats a 204 or empty response body as `None`** instead of calling `.json()` on it (which would raise). Needed for `delete_webhook` (204 No Content) and safe for `publishing_succeeded` / `publishing_failed` in case Printify returns an empty ack body for those too.
- **`register_printify_webhooks` assumes Printify's `GET /shops/{shop_id}/webhooks.json` returns a flat list**, not the Laravel-style paginated envelope used by the products list endpoint. This matches Printify's documented webhook API shape, but like the shipment payload above, it's unverified against a live call in this session. The command defensively checks `isinstance(existing, list)` and falls back to `.get('data', [])` if it turns out to be wrapped after all.
- **Admin's "recent webhook events" panel uses `payload__icontains` on the JSONField**, matching against the order's `printify_order_id` as a substring of the stored JSON. There's no FK from `WebhookEvent` to `Order` (the only link is whatever ID appears inside the JSON payload), so this is a best-effort text search, not a real join. Wrapped in a try/except that degrades to "no events" rather than a 500 if a given DB backend's JSONField doesn't support `icontains` the way SQLite/Postgres do.
- **`PRINTIFY_HANDLED_EVENT_TYPES` frozenset mirrors Sprint 3's `STRIPE_HANDLED_EVENT_TYPES` pattern exactly**, per the prompt's explicit instruction. Seven entries: four `order:*` + three `product:*`. `register_printify_webhooks.DESIRED_TOPICS` must be kept in sync with this list by hand — there's no shared constant between `orders/views.py` and the management command (`orders` importing from a management command's module, or vice versa, seemed like the wrong direction of coupling; a future refactor could hoist the topic list into `orders/models.py` or a small `constants.py` if this becomes a maintenance annoyance).
- **Discovered while editing `orders/views.py`: several docstrings and inline strings in the existing Sprint 2/3 code contain a literal `\u2014` escape sequence (six characters: backslash, u, 2, 0, 1, 4) instead of an actual em dash character.** This looks like an artifact from an earlier AI-assisted edit that wrote the Python source of a Unicode escape rather than the Unicode character itself — Python still runs fine since it's just an odd-looking substring inside a string/comment, but it renders as literal `\u2014` text if that comment or docstring is ever surfaced verbatim (e.g. in generated docs). Did not do a blanket find/replace across the existing codebase since that's a cosmetic, pre-existing issue outside Sprint 4's scope — flagging here so it doesn't get mistaken for something Sprint 4 introduced. All *new* Sprint 4 code uses plain ASCII (`--`) or real em dash characters, not escaped sequences.
- **No automated tests were added.** The sprint plan doesn't ask for them and the existing codebase has none (`smoke_tests/` in HuntScrape's repo is the only precedent, and it's a separate manual-run harness, not pytest/Django TestCase). Verification is manual, per the acceptance criteria and the operational follow-up below.
- **Operational follow-up (not fully verifiable from this session — network access to Printify/Stripe/Heroku is not available to Claude in this environment):**
  1. Set `PRINTIFY_WEBHOOK_SECRET` in Heroku config (`heroku config:set PRINTIFY_WEBHOOK_SECRET=...`) using the same value now in local `.env`, or generate a separate production secret and re-run `register_printify_webhooks` in production after deploy.
  2. Run `python manage.py register_printify_webhooks --brand=chesco.io` (add `--dry-run` first to review the plan) once the app is deployed with this sprint's code, so Printify actually starts delivering the seven handled event types to `/webhooks/printify/`.
  3. Place a real Stripe test-mode order end-to-end and watch `heroku logs --tail --app chescoio` per the prompt's step 12: confirm the Printify order gets created, `printify_order_id` gets stored, the confirmation email queues and sends, and — critically — check the actual JSON shape of the `order:shipment:created` webhook payload against the guesses in `_handle_printify_order_shipped` (see note above).
  4. Click "Publish" on a test product in Printify and time how long it takes to appear on `/shop/`; verify the product card unlocks in Printify's UI afterward (confirms `publishing_succeeded` is accepted with an empty body, per the open question above).
  5. Run `python manage.py send_mail` and `python manage.py retry_deferred` manually once locally to confirm the django-mailer queue actually drains (per prompt step 6), then wire the Heroku Scheduler job (`python manage.py send_mail && python manage.py retry_deferred`, every 10 minutes — Heroku Scheduler's tightest interval) before relying on it for real customers.
  6. Verify DKIM/SPF/DMARC on the `hello@chesco.io` sending domain via mail-tester.com or equivalent, per the prompt's step 5 and the launch-blocker note in "critical reminders." This is unverified and was explicitly called out as a potential launch blocker in the prompt — don't skip it.
  7. `python manage.py makemigrations --check` and `python manage.py migrate` should be run locally to confirm migration `orders/0003_order_email_dedupe_guards.py` applies cleanly — it was hand-written in this session (no Django management command was run to generate it, since this session's tools operate on the Windows filesystem directly and can't execute `manage.py` in that environment) and mirrors the style of the Sprint 3 migration, but hasn't been run against the actual dev database.
  8. Commit and push to GitHub `main` once the above verification passes.

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
