# Sprint 4 Implementation Prompt — Printify Order Submission, Status Sync & Product Webhooks

## Context

You are implementing Sprint 4 of the East Goshen Apparel Platform. Sprints 1-3 are complete:

- App deployed at `https://www.chesco.io` (custom domain, ACM SSL, apex→www canonicalization live)
- Products syncing from Printify (`sync_printify_products` command, hourly Heroku Scheduler job pending Sprint 5 wiring)
- Cart, Stripe Checkout, and webhook handler working end-to-end in production (Stripe test mode); Orders materialize on `checkout.session.completed`
- Stripe webhook endpoint registered in production dashboard, PA clothing tax exemption verified ($0.00 tax on clothing)
- Sprint 3 shipped a lot of hard-won patterns (webhook filter frozenset, defensive metadata handling, HTMX OOB swap gating, CSS var fallbacks) — **read the Sprint 3 delivery notes in `eg_apparel_sprint_plan.md` before starting**. They document landmines you must not step on again and patterns you should reuse verbatim.

The developer is John (East Goshen Technologies). Project at `C:\django\prod-django\chescoio\`. Filesystem MCP workflow, direct recommendations preferred, honest pushback valued.

## Sprint 4 goal

Wire up the fulfillment side AND make new-product publishing feel instant:

1. **Fulfillment**: paid orders auto-submit to Printify, Printify webhooks update local order status, customers get transactional emails at key milestones. By end of sprint, a successful Stripe checkout should result in a Printify order being placed within 30 seconds, a confirmation email being sent immediately, and a shipped email being sent when Printify provides tracking.

2. **Product publishing**: clicking "Publish" on a new product in Printify should make it appear on `https://www.chesco.io/shop/` within seconds via the `product:publish:started` webhook, and unlock the product card in Printify's UI via the `publishing_succeeded` callback. The hourly Scheduler sync becomes the safety net rather than the primary path.

## Pre-work (do this first, in order)

1. Read the full sprint plan, focusing on the Sprint 4 section and re-reading the order pipeline diagram. **Read the Sprint 3 delivery notes carefully** — they contain landmines, patterns, and operational preconditions that materially affect Sprint 4.
2. Read the Printify webhooks documentation. Note the event types (order:* AND product:*), the payload structure, the signature header name (`X-Pfy-Signature`), and the signing method (HMAC-SHA256 with the `sha256=` prefix).
3. Read HuntScrape's django-mailer setup — the queue draining pattern, the Scheduler job, the template rendering approach for transactional emails. django-mailer is already installed in chescoio from Sprint 1; only the queue-drain scheduler job and the templates are missing.
4. **Generate a Printify webhook signing secret** and store it (`PRINTIFY_WEBHOOK_SECRET` in both `.env` and `heroku config:set`). Unlike Stripe (dashboard-generated), Printify webhook secrets are values *we* generate and pass in when registering the webhook via API — Printify echoes the secret back in the HMAC on every delivery. Any strong random string works; `python -c "import secrets; print(secrets.token_urlsafe(32))"` is fine.
5. Verify DKIM/SPF/DMARC on `hello@chesco.io` (or whichever from-email you're using). Hostinger's SMTP is set up but may not have DNS auth records configured for the chesco.io domain specifically. Test via https://mail-tester.com before relying on email delivery.
6. Send a test email through django-mailer in dev to verify the pipeline works before wiring transactional emails to real order events. Sprint 3 shipped the mailer install; nothing has actually queued or sent an email yet.
7. **Sprint 3 already extracted `sync_one_product(brand, product_data)` into `catalog/services.py`**. Sprint 4's `product:publish:started` handler reuses that function directly — don't rewrite the upsert logic.

## Implementation order

Work in this sequence and commit after each step:

1. **Order submission service** — add `submit_order_to_printify(order)` to `orders/checkout_services.py` (keeps all Stripe / Printify order-shape logic in one module; alternative is a new `orders/fulfillment_services.py` if the file gets unwieldy). Build the Printify order payload per the sprint plan, call the API via the existing `PrintifyClient`, store the returned `printify_order_id`, update status to `submitted`. Wrap in try/except. On failure, set status to `submission_failed`, log full error context, queue an admin alert email.

2. **Wire submission into Stripe webhook** — after the local Order is created in `orders/views.py::_handle_checkout_completed` (Sprint 3 code), call `submit_order_to_printify(order)`. Synchronous within the webhook handler so failures surface immediately in Stripe's dashboard event log. Sprint 3's soft-skip logic for missing metadata already returns `None` from `create_order_from_stripe_session` in the non-our-session case — gate the Printify submission on the return value being a real Order, not `None`.

3. **Email templates** — create three templates with both `.txt` and `.html` versions:
   - `emails/order_confirmation.{txt,html}` — sent immediately after Order creation
   - `emails/order_shipped.{txt,html}` — sent when Printify provides tracking
   - `emails/admin_order_failed.txt` — sent to support email on submission failure
   Brand-aware: use `order.brand.name`, `order.brand.from_email`, `order.brand.support_email`, `order.brand.primary_color` in the templates. **Note**: `templates/orders/_checkout_success_status.html` already displays "A confirmation will arrive at {{ order.email }} shortly" as a known-lie promise from Sprint 3. Shipping the confirmation email in this step makes that copy honest — first thing to verify at end of sprint.

4. **Email sending helpers** — `orders/emails.py` with functions like `send_order_confirmation(order)` and `send_order_shipped(order)`. All emails go through django-mailer's `mail.send()` (queued to DB, not direct send). Mirror HuntScrape's pattern.

5. **Mailer queue drain job** — Heroku Scheduler job running `python manage.py send_mail && python manage.py retry_deferred` every 10 minutes (the tightest interval Heroku Scheduler supports). Per the HuntScrape pattern. Verify the queue drains by sending a test email and watching it process. Sprint 5's launch checklist tracks Scheduler wiring formally, but the send_mail job needs to work by end of Sprint 4 for the acceptance criteria to pass.

6. **Printify webhook signature verification + event filter** — in `orders/views.py::printify_webhook` (Sprint 2 stub), implement HMAC-SHA256 signature verification using `PRINTIFY_WEBHOOK_SECRET`. Header is `X-Pfy-Signature`, format is `sha256={hexdigest}`. Use `hmac.compare_digest` for the comparison (timing-safe). Reject with 403 if signature doesn't match.

   **Add a `PRINTIFY_HANDLED_EVENT_TYPES` frozenset** mirroring Sprint 3's `STRIPE_HANDLED_EVENT_TYPES` pattern. Contents: the four order events + three product events (see step 7 and step 8). Every other event type short-circuits to a 200 without DB writes or handler dispatch. This is the Sprint 3 pattern for the same reasons — avoid audit-log noise, avoid serialization edge cases from event shapes we never look at.

7. **Order event handlers** — per the sprint plan, handle:
   - `order:sent-to-production` → status = `in_production`, no customer email by default (noisy)
   - `order:shipment:created` → status = `shipped`, extract tracking number + URL + carrier, send shipped email
   - `order:shipment:delivered` → status = `delivered`, no customer email by default
   Each handler is idempotent via the WebhookEvent `(source, event_id)` uniqueness check at the top of the dispatch function — same pattern as the Stripe webhook handler.

8. **Product event handlers** — handle:
   - `product:publish:started` → fetch the product from Printify via `PrintifyClient.get_product`, call `catalog.services.sync_one_product(brand, product_data)` (already exists from Sprint 3), then call `PrintifyClient.publishing_succeeded(shop_id, product_id)` on success or `PrintifyClient.publishing_failed(shop_id, product_id, reason=...)` on exception. Synchronous — acknowledge the webhook only after the sync + callback completes. This unlocks the product card in Printify's UI.
   - `product:publish:succeeded` → logging only, no state change (our sync already ran in the previous handler)
   - `product:deleted` → mark local Product as `is_published=False`

   Add `publishing_succeeded` and `publishing_failed` methods to `PrintifyClient` in `catalog/printify_client.py` — they weren't needed until Sprint 4. Endpoints per the sprint plan.

   **Defensive detail**: if a `product:publish:started` fires for a shop_id we don't have a Brand for, log a warning and return 200. Don't 500 (would trigger retry storms).

9. **Tracking number storage** — add fields to Order: `tracking_number`, `tracking_url`, `carrier`, `shipped_at`. Migration required. Populate from the `order:shipment:created` webhook payload.

10. **Admin enhancements** — in Django admin, show order status, Printify order ID, tracking info. Add an admin action "Retry Printify submission" for orders in `submission_failed` state. Add a read-only display of the most recent webhook events related to the order.

11. **`register_printify_webhooks` management command** — there is no Printify dashboard UI for webhooks; registration is API-only via `POST /v1/shops/{shop_id}/webhooks.json`. Build the command per sprint plan deliverable #11: list existing webhooks for the brand's shop, compute the desired set (all four order:* topics + three product:* topics, all pointing at `https://www.chesco.io/webhooks/printify/`, all using `PRINTIFY_WEBHOOK_SECRET`), create missing, update stale URLs, leave correct ones alone. Support a `--prune` flag to delete stray subscriptions. Idempotent — re-running produces no duplicates.

    Same structural template as `scripts/configure_stripe_dev.py` from Sprint 3: list current state, compute diff, apply changes, print summary.

12. **End-to-end test** — place a real Stripe TEST order on `https://www.chesco.io`. Watch `heroku logs --tail --app chescoio`:
    - Stripe webhook fires → Order created → submission to Printify called → `printify_order_id` stored
    - Order confirmation email queued → drained by mailer → arrives in your inbox
    - Wait for Printify to process the order in their dashboard, or use their test mode if available
    - Printify webhook fires as order moves through production/shipped/delivered
    - Status updates locally → shipped email arrives with tracking link

    Separately: click Publish on a new product in Printify and time how long it takes to appear on `/shop/`. Should be < 10 seconds end to end.

13. **Verify acceptance criteria** — run through all ten Sprint 4 acceptance criteria from the sprint plan.

## Critical reminders

- **Synchronous submission is intentional.** The order submission to Printify happens inside the Stripe webhook handler so failures are visible immediately. If you move this to a background task, you trade latency for observability — don't do that without a clear reason.
- **Synchronous product sync too.** The `product:publish:started` handler acknowledges only after `sync_one_product` + `publishing_succeeded` completes. For a single product that's typically 2-3 Printify API calls plus a DB transaction — well under Printify's webhook timeout.
- **HMAC comparison must be timing-safe.** Use `hmac.compare_digest`, never `==`. Direct string comparison leaks timing information that can be used to forge signatures.
- **Idempotency in Printify webhooks too.** Same pattern as Stripe: `(source, event_id)` uniqueness lookup on `WebhookEvent` before processing. Printify will replay webhooks on delivery failure.
- **Apply the `STRIPE_HANDLED_EVENT_TYPES` frozenset pattern to Printify.** Sprint 3 short-circuits noise events to a 200 without DB writes; do the same for Printify. `PRINTIFY_HANDLED_EVENT_TYPES = frozenset({...})` covering exactly the seven event types you handle. Everything else 200s immediately.
- **Soft-skip events for shops we don't own.** Sprint 3's `create_order_from_stripe_session` returns `None` + logs a warning when `metadata.brand_id` is missing rather than raising (which would trigger retry storms). Apply the same defensive pattern for Printify: if `product:publish:started` references a shop_id we can't map to a Brand, log warning and 200.
- **Email DKIM/SPF/DMARC must pass before launch.** Use https://mail-tester.com or similar to verify. Without proper auth, emails land in spam, and customers won't get their order confirmations. This is a launch blocker.
- **Address validation matters here.** A bad shipping address is the most common Printify rejection. The Stripe Checkout collected address should be clean, but if Printify rejects it (validation in their API), the order ends up in `submission_failed` and the customer has paid but won't receive anything. Admin alert email exists for exactly this reason — handle these manually within hours of receipt, not days.
- **The customer paid before Printify confirmed.** This is by design — Stripe payment first, Printify submission second. If Printify rejects the order, you have a paid customer and no fulfillment. Manual intervention required: contact the customer, fix the address, resubmit. Document this workflow in the admin retry action.
- **Don't double-send emails on webhook replay.** The idempotency check prevents double-processing, but be especially careful with the email-sending side. Email queue send should be inside the WebhookEvent transaction OR gated on a `notification_sent_at` timestamp field per order state.
- **Brand-aware everything.** Email templates render the brand's name, colors, support email. Never hardcode "Chesco" or "Chester County Apparel Co." — use `order.brand.name`. Sprint 5 may introduce a second brand and your email templates must handle that.

**Sprint 3 landmines that will re-appear if you're not careful** (all documented in more depth in Sprint 3 delivery notes):

- **Multi-line `{# ... #}` Django comments leak as visible text on the rendered page.** Bit us three times in Sprint 3. Rule: `{# ... #}` for single-line comments only; `{% comment %}...{% endcomment %}` for anything spanning lines.
- **HTMX OOB swap conflicts.** If any Sprint 4 email preview / admin fragment reuses a partial as both primary target and OOB target, gate the `hx-swap-oob` attribute conditionally via context flag — don't hardcode it.
- **CSS variable hex fallbacks.** Any new inline `<style>` block using `var(--color-brand-*)` needs a hex fallback: `background-color: var(--color-brand-primary, #1a4d2e);`. Applies to any brand-styled email HTML template too.

## When to ask, when to act

**Just do** — anything in the sprint plan, anything mirroring HuntScrape's email patterns, anything covered by acceptance criteria, anything that reuses a Sprint 3 pattern verbatim (webhook filter frozenset, defensive metadata handling, `sync_one_product` reuse).

**Ask first** — any decision about whether to send the "in production" or "delivered" emails to customers (default: no, noise — only confirmation and shipped), any decision about retry intervals for failed Printify submissions (default: manual retry only, no automatic retry to avoid duplicate orders), any decision about Printify webhook events beyond the seven specified in Sprint 4 deliverables (the others are mostly noise for v1).

**Push back if** — Printify's API rejects test orders in ways that suggest the order payload structure has changed from the docs (this happens), the webhook signature verification fails consistently (could be encoding issue or wrong secret), or the email deliverability is poor and DKIM/SPF setup is the actual blocker — flag that and stop before launch.

## Definition of done

Sprint 4 is complete when:

- All eleven Sprint 4 deliverables from the sprint plan are met
- All ten acceptance criteria pass
- A test order has been placed end-to-end and produced a real Printify order (Stripe test mode is fine; live mode flip is Sprint 5)
- Order confirmation email arrived in inbox, passed DKIM/SPF/DMARC checks at mail-tester.com or equivalent
- Forced Printify webhook replay did not duplicate state changes or emails
- Publishing a new product in Printify caused it to appear on `/shop/` within 10 seconds
- The product card in Printify's UI unlocks after `publishing_succeeded` fires
- Code is on `main` in GitHub, deployed to Heroku
- Sprint 4 delivery notes appended to `eg_apparel_sprint_plan.md`, following the format Sprints 1-3 established. Capture: Printify webhook payload shape quirks discovered, email deliverability fixes, any Printify order-submission edge cases, any patterns worth extracting for Sprint 5.
