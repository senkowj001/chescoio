# Sprint 3 Implementation Prompt — Cart & Stripe Checkout

## Context

You are implementing Sprint 3 of the East Goshen Apparel Platform. Sprints 1-2 are complete: multi-brand app deployed, Printify products syncing hourly (revised from nightly), product list and detail pages live at `https://chesco.io/shop/`. The full sprint plan is in `eg_apparel_sprint_plan.md` — read it before starting.

The developer is John (East Goshen Technologies). Project at `C:\django\prod-django\chescoio\`. Filesystem MCP workflow, direct recommendations preferred, honest pushback valued.

## Sprint 3 goal

Build the cart and checkout flow, and add an admin "Sync Now" action for operator-driven product syncs. By end of sprint: customers can add products to cart, view cart, click checkout, get redirected to Stripe Checkout with line items + dynamic shipping rates + Stripe Tax enabled, and successful payments create Order records locally via webhook. Printify order submission and product-publish webhooks happen in Sprint 4 — don't do them here.

## Pre-work (do this first, in order)

1. Read the full sprint plan, focusing on "Sprint 3" and the order pipeline diagram
2. Read HuntScrape's Stripe integration code in detail — checkout session creation, webhook handling, signature verification. That is your template.
3. Read Stripe's current docs on: Checkout Sessions, Stripe Tax automatic mode, shipping_options, webhook signing. Specifically confirm the current API for `automatic_tax` and `shipping_address_collection` since these change.
4. Confirm with John: whether Stripe account is in live or test mode for development, whether Stripe Tax is registered for PA already, and whether the webhook signing secret has been generated
5. Test a Printify shipping rate API call manually (curl or Python notebook) to understand the response shape before coding against it

## Implementation order

Work in this sequence and commit after each step:

1. **Cart models** — `Cart` and `CartItem` per sprint plan. Session-keyed, not user-keyed. Add a `clear_old_carts` management command that deletes carts older than 7 days (matches the canonical models inventory; supersedes the earlier 30-day reference). Wire it up as a Heroku Scheduler job in Sprint 5 / launch checklist time, not now.

2. **Cart views (HTMX)** — Add to cart, update quantity, remove from cart. All HTMX endpoints returning fragments that swap into the page. The mini-cart in the header updates via `hx-trigger` on cart events. Mirror HuntScrape's HTMX patterns for consistency.

3. **Cart page** — `/cart/` route. Shows line items with product image, title, variant (size/color), quantity stepper, line subtotal, and a "Remove" action. Shows order subtotal at bottom. "Proceed to checkout" button if cart is non-empty. Empty state if cart is empty.

4. **ZIP entry on cart page** — Before showing the checkout button, ask for ZIP code. On submit, call Printify shipping rate API to get rate options. Store the rate(s) in the session, show them to the customer on the cart page, then enable the checkout button. This is the v1 approach per the sprint plan — fixed rates passed to Stripe, not real-time rates at Stripe checkout.

5. **Stripe Checkout session creation** — `/checkout/` POST route. Builds line items from cart, builds shipping_options from cached Printify rates, creates Stripe Checkout session with `automatic_tax.enabled=True` and `shipping_address_collection.allowed_countries=["US"]`. Stores cart ID and brand ID in session metadata so the webhook can resolve them. Redirects to `session.url`.

6. **Success and cancel pages** — `/checkout/success/?session_id=...` looks up the local order (or shows "processing" if the webhook hasn't landed yet) and renders order detail. `/cart/` is the cancel URL (per the sprint plan). Success page should poll via HTMX every 2 seconds for up to 30 seconds if the order isn't yet created, then show a "we got your payment, confirmation is processing" message.

7. **Order and OrderItem models** — Per the sprint plan. `Order` captures full shipping address, contact info, brand, status, totals, shipping method code, Stripe session ID, Printify order ID (nullable for now). `OrderItem` captures variant, quantity, unit price snapshot, line total. Snapshot prices at order time — never query Variant for the price after order creation.

8. **Reuse the existing WebhookEvent model from Sprint 2.** `WebhookEvent` was created in Sprint 2 (`orders/models.py`) as a shared idempotency / audit log for both Stripe and Printify. It has `source` (choices: `stripe`, `printify`), `event_id`, `event_type`, `payload` (JSON), `received_at`, `processed_at`, `error`. Uniqueness is on `(source, event_id)`. Stripe events go in as `source=WebhookEvent.SOURCE_STRIPE`. *Do not rebuild this model.*

9. **Stripe webhook endpoint** — `/webhooks/stripe/` POST route. Verify signature, check idempotency against `WebhookEvent` (filter on `source=WebhookEvent.SOURCE_STRIPE, event_id=event["id"]`), handle `checkout.session.completed` by creating the local Order record from the session data. Set `processed_at` when the handler completes. Return 200 on success and on already-processed events.

10. **Test order end-to-end** — Use Stripe test mode and Stripe's test card numbers. Place a test order, verify Order appears in admin with all fields correct. Force a duplicate webhook delivery (Stripe dashboard "resend") and verify it does NOT create a duplicate Order.

11. **Verify acceptance criteria** — Run through Sprint 3 acceptance criteria from the sprint plan.

12. **Admin "Sync Now" action on Brand** — Per Sprint 3 deliverable #11 and sprint plan section 3.5. Add a Django admin action on the `Brand` model that calls the existing `sync_printify_products` management command synchronously for each selected brand. Surface success / failure / product count via `self.message_user`. Skip brands without a `printify_shop_id` with a warning message. This is small — maybe 30 minutes including admin styling — and unrelated to the cart/checkout work, so it can be done first as a warm-up or last as cleanup. Doesn't matter when, as long as it ships with Sprint 3.

## Critical reminders

- **Idempotency is non-negotiable.** WebhookEvent table is the single source of truth for "did we already process this." Check it first thing in the webhook handler. Always include `source=WebhookEvent.SOURCE_STRIPE` (or `SOURCE_PRINTIFY` in Sprint 4) in both the filter and the create — uniqueness is on the pair, not on event_id alone.
- **Signature verification before any logic.** A webhook handler that processes payloads before verifying the signature is a vulnerability. Always verify first, then check idempotency, then process.
- **Price snapshots in OrderItem.** When the customer pays $24.99 for a shirt, the OrderItem stores 2499 cents permanently. If you change the Variant price tomorrow, the historical order must still show $24.99.
- **PA clothing tax exemption.** Stripe Tax handles this automatically when products are correctly categorized. Verify the tax preview shows $0.00 tax for a PA shipping address before launch. If it doesn't, the issue is product tax category in Stripe — not a code issue.
- **Stripe Tax registration is a real-world step.** John needs to actually register PA in the Stripe Tax settings before tax calculations work. Confirm this is done; if not, flag it.
- **Guest checkout means no User FK on Order.** The Order has an email field. That's the only customer identifier. Don't sneak in a User foreign key "just in case."
- **Cart cleanup on order success.** When the Stripe webhook creates the Order, delete the Cart. Don't leave orphaned carts littering the database.
- **Session expiry.** Carts are session-keyed. If the session expires, the cart is orphaned. The 7-day cleanup task handles this. Django's default `SESSION_COOKIE_AGE` is 14 days, so a returning visitor between day 7 and day 14 may have an intact session but an empty cart — that's intentional, not a bug.

## When to ask, when to act

**Just do** — anything in the sprint plan, anything mirroring HuntScrape's Stripe patterns, anything covered by acceptance criteria.

**Ask first** — anything about Stripe Tax behavior in edge cases (multi-state orders, business customer vs. consumer), any change to how shipping_options are constructed, any decision about whether to support Apple Pay / Google Pay (default: yes, Stripe Checkout enables these automatically), any decision about whether to require a phone number at checkout (default: optional).

**Push back if** — the shipping rate flow from Printify creates UX friction that's worse than worth it (in which case, propose Option B from the sprint plan instead), the Stripe Tax calculation doesn't match expectations (could be a product categorization issue or a registration issue), or the cart abandonment rate during testing seems unusually high (could indicate a checkout flow problem).

## Definition of done

Sprint 3 is complete when:

- All eleven Sprint 3 deliverables from the sprint plan are met
- All nine acceptance criteria pass on production (Stripe in TEST mode for now — live mode flip is in Sprint 5)
- A test order placed via Stripe test cards creates an Order record correctly
- A replayed webhook does not duplicate the order
- PA shipping address shows $0.00 sales tax for clothing
- Code is on `main` in GitHub
- Sprint plan updated with any new learnings about Stripe Tax, shipping rate quirks, or Stripe Checkout API behavior that affect Sprint 4 or 5
