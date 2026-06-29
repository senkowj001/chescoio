# Sprint 2 Implementation Prompt — Printify Integration

## Context

You are implementing Sprint 2 of the chescoio apparel platform (Chester County Apparel Co., the first brand front on a multi-brand Django backend). Sprint 1 is complete: multi-brand Django app deployed to Heroku as the `chescoio` app, `chesco.io` resolves to a branded "Coming Soon" page, Brand model and middleware are working. The full sprint plan is in `sprintplans/eg_apparel_sprint_plan.md` — read it before starting, including the **"Sprint 1 — delivery notes"** subsection at the end of the Sprint 1 section, which documents architectural deviations from the original plan (Django 5.2.12 LTS pin, no Cloudflare, no staging environment, Tailwind v4 with `@theme` tokens, `BrandMiddleware` DEBUG fallback, settings filenames `local.py` / `production.py`).

The developer is John (East Goshen Technologies). Project lives at `C:\django\prod-django\chescoio\`. The Django project module is `chescoio` (not `eg_apparel`). He uses filesystem MCP for direct editing, prefers direct recommendations, and values honest pushback on flawed plans.

## Sprint 2 goal

Build the Printify integration layer: a service client, models for Product/Variant/ProductImage, a sync command, a nightly Heroku Scheduler job, and product list + detail views. By the end of this sprint, visiting `https://chesco.io/shop/` should show real products synced from Printify, and `/shop/<slug>/` should show product detail with a working variant selector. No cart yet.

## Pre-work (do this first, in order)

1. Read the full sprint plan, focusing on "Sprint 2", the "Sprint 1 — delivery notes" subsection, and the Printify section under "Order pipeline". Note that the "Reusable code patterns" section at the bottom of the plan has been corrected with actual directory names.
2. Read the Printify API documentation at `https://developers.printify.com/` — specifically the products, shipping, and orders endpoints. Note rate limits (600/min, 200/30s on catalog).
3. Confirm with John: the Printify shop ID for `chesco.io`, whether the personal access token has been generated, and whether sample products already exist in the Printify shop or need to be created for testing. **Important**: the Sprint 1 Brand seed left `Brand.printify_shop_id` blank by design (it's an integration secret, not a brand identity field). Populate it via Django admin (or a new data migration) before running the sync command.
4. Read Apeirum's API client patterns for retry-with-backoff and error handling. **Apeirum lives at `C:\django\prod-django\myticker\`** (the directory name reflects the project's pre-rebrand identity; the live app is Apeirum.io). Look for FMP client and Claude client modules there.
5. Read the existing `Brand` model at `brands/models.py` and confirm Sprint 1 state. Note that the `catalog` app already exists as a placeholder scaffold (`__init__.py`, `apps.py`, empty `models.py`, `migrations/__init__.py`) — do NOT run `python manage.py startapp catalog`; just add models and other modules to the existing folder.
6. Skim `templates/base.html` to understand the styling system in place: Tailwind v4 via `@tailwindcss/browser@4` with `@theme` design tokens. Brand colors are exposed as Tailwind utilities (`bg-brand-primary`, `text-brand-accent`, etc.) and as raw CSS vars (`var(--color-brand-primary)`, `var(--color-brand-accent)`). All Sprint 2 product templates should extend `base.html` and use this system — do not introduce a parallel styling approach.

## Implementation order

Work in this sequence and commit after each step:

1. **Models** — Implement `Product`, `Variant`, `ProductImage` exactly as specified in the sprint plan, in the existing `catalog` app. Run migrations locally first, verify the schema, commit, then `git push heroku main` — the Procfile release phase runs `migrate --noinput` automatically. (No staging environment per the Sprint 1 delivery notes: dev → prod direct.)

2. **Printify client** — Build `catalog/printify_client.py` with the methods from the sprint plan. Include retry-with-backoff on 429 responses (mirror Apeirum's pattern). All requests go through a single `_request` method with timeout, logging, and error handling. Add `PRINTIFY_ACCESS_TOKEN` to env vars.

3. **Sync management command** — `catalog/management/commands/sync_printify_products.py`. Accepts `--brand=<domain>` argument. Pulls all products page by page, upserts into local DB inside a transaction per product. Marks variants no longer in Printify as `is_enabled=False` rather than deleting (preserves order history references). Log counts at the end: products created, updated, variants disabled.

4. **Manual sync test** — Run the command locally against the live Printify shop. Verify products appear in Django admin with all fields populated correctly, including images.

5. **Product list view** — `/shop/` route, lists all `is_published=True` products for `request.brand`. Card layout, primary image, title, starting price ("from $X.XX"). HTMX-ready but no interactions yet.

6. **Product detail view** — `/shop/<slug>/` route. Renders product description, image gallery (default image first), variant selector (size + color dropdowns), price that updates based on selected variant. Out-of-stock variants disabled in dropdown. Add-to-cart button is present but disabled (cart comes in Sprint 3).

7. **Size guide partial** — Pull garment measurements from Printify's blueprint data (you may need to call a separate Printify endpoint to get blueprint details). Format as a clear HTML table. Link from each product page.

8. **Heroku Scheduler job** — Add a daily job at 03:00 UTC: `python manage.py sync_printify_products --brand=chesco.io`. Verify it runs successfully via Heroku logs.

9. **Webhook endpoint stub** — Create `/webhooks/printify/` route that returns 200 and logs the payload to `WebhookEvent`. Full handling comes in Sprint 4, but the endpoint needs to exist now so the URL can be registered in Printify.

10. **Verify acceptance criteria** — Run through Sprint 2 acceptance criteria from the sprint plan.

## Critical reminders

- **Idempotency in sync.** The sync command must be safely re-runnable. Use `update_or_create` on `printify_product_id`. Never duplicate.
- **Transaction safety.** Each product sync (product + variants + images) is one transaction. If any part fails, the whole product rolls back. Partial syncs corrupt data.
- **Image URLs are Printify-hosted.** Do not download and re-host images yet. Just cache the URLs. Self-hosting is a 2.0 concern when image bandwidth becomes a cost.
- **Rate limit awareness.** With 600 req/min, syncing 100 products with their variant detail calls could approach limits. Use the paginated list endpoint efficiently and only fetch product detail when you actually need variant data not in the list response.
- **Watch for blueprint changes.** Printify occasionally updates blueprint definitions. The sync should handle a blueprint_id change on an existing product gracefully (log a warning, do not silently overwrite).
- **No price markup logic in code.** The retail price comes from Printify (where John has set the markup in the Printify dashboard). The Django side just stores what Printify returns. Do not introduce a separate markup field.

## When to ask, when to act

**Just do** — anything in the sprint plan, anything mirroring existing East Goshen patterns, anything covered by acceptance criteria.

**Ask first** — Printify API endpoint behavior that's ambiguous from the docs (test in a notebook first if uncertain), any deviation from the model definitions in the sprint plan, any caching strategy beyond what the plan specifies, any decision about how to handle Printify's "blueprint" vs. "print provider" hierarchy if it creates more complexity than expected.

**Push back if** — Printify's API returns data in a shape that breaks the model design, the sync command runs slower than expected (>5 min for 50 products), or the variant matching logic is more complex than the plan accounts for.

## Definition of done

Sprint 2 is complete when:

- All ten Sprint 2 deliverables from the sprint plan are met
- All six acceptance criteria pass on production
- Nightly scheduler runs successfully at least once with no errors
- Code is on `main` in GitHub
- The sprint plan document is updated with any decisions, gotchas, or deviations encountered (especially anything about Printify API quirks that future sprints need to know)
