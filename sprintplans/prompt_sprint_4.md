# Sprint 4 Implementation Prompt — Printify Order Submission & Status Sync

## Context

You are implementing Sprint 4 of the East Goshen Apparel Platform. Sprints 1-3 are complete: app deployed, products syncing, cart and Stripe Checkout working in test mode, Orders are created locally from successful payments. The full sprint plan is in `eg_apparel_sprint_plan.md` — read it before starting.

The developer is John (East Goshen Technologies). Project at `C:\django\prod-django\eg_apparel\`. Filesystem MCP workflow, direct recommendations preferred, honest pushback valued.

## Sprint 4 goal

Wire up the fulfillment side: paid orders auto-submit to Printify, Printify webhooks update local order status, customers get transactional emails at key milestones. By end of sprint, a successful Stripe checkout should result in a Printify order being placed within 30 seconds, a confirmation email being sent immediately, and a shipped email being sent when Printify provides tracking.

## Pre-work (do this first, in order)

1. Read the full sprint plan, focusing on "Sprint 4" and re-reading the order pipeline diagram
2. Read the Printify webhooks documentation. Note the event types, the payload structure, the signature header name, and the signing method (HMAC-SHA256).
3. Read HuntScrape's django-mailer setup — the queue draining pattern, the Scheduler job, the template rendering approach for transactional emails
4. Confirm with John: Printify webhook signing secret has been generated and stored, the support email (`hello@chesco.io` or whatever) has working DKIM/SPF/DMARC configured, and the from-email matches the brand's `from_email` field
5. Send a test email through django-mailer in dev to verify the pipeline works before relying on it

## Implementation order

Work in this sequence and commit after each step:

1. **Order submission service** — `orders/services.py` with `submit_order_to_printify(order)` function per the sprint plan. Build the Printify order payload, call the API, store the returned `printify_order_id`, update status to "submitted". Wrap in try/except. On failure, set status to "submission_failed", log full error context, queue an admin alert email.

2. **Wire submission into Stripe webhook** — After the local Order is created in the `checkout.session.completed` handler from Sprint 3, call `submit_order_to_printify(order)`. This must happen synchronously within the webhook handler so a failure surfaces immediately. Keep the webhook idempotency check in place.

3. **Email templates** — Create three templates with both `.txt` and `.html` versions:
   - `emails/order_confirmation.{txt,html}` — sent immediately after Order creation
   - `emails/order_shipped.{txt,html}` — sent when Printify provides tracking
   - `emails/admin_order_failed.txt` — sent to support email on submission failure
   Brand-aware: use `request.brand`'s from_email, support_email, name, primary_color in the templates.

4. **Email sending helpers** — `orders/emails.py` with functions like `send_order_confirmation(order)` and `send_order_shipped(order)`. All emails go through django-mailer's `mail.send()` (queued, not direct send). Mirror HuntScrape's pattern.

5. **Mailer queue drain job** — Heroku Scheduler job running `python manage.py send_mail && python manage.py retry_deferred` every 15 minutes. Per the HuntScrape pattern. Verify the queue actually drains by sending a test email and watching it process.

6. **Printify webhook signature verification** — In `/webhooks/printify/` (the stub from Sprint 2), implement HMAC-SHA256 signature verification using `PRINTIFY_WEBHOOK_SECRET`. Use `hmac.compare_digest` for the comparison (timing-safe). Reject with 403 if signature doesn't match.

7. **Printify webhook event handlers** — Per the sprint plan, handle:
   - `order:sent-to-production` → status = "in_production", optionally email customer
   - `order:shipment:created` → status = "shipped", extract tracking number and URL, send shipped email
   - `order:shipment:delivered` → status = "delivered", optionally email customer
   Each handler is idempotent via the WebhookEvent table check at the top of the dispatch function.

8. **Tracking number storage** — Add fields to Order: `tracking_number`, `tracking_url`, `carrier`, `shipped_at`. Populate from the `order:shipment:created` webhook payload.

9. **Admin enhancements** — In Django admin, show order status, Printify order ID, tracking info. Add an admin action "Retry Printify submission" for orders in `submission_failed` state. Add a read-only display of the most recent webhook events related to the order.

10. **Register Printify webhook** — In the Printify dashboard, register the webhook URL `https://chesco.io/webhooks/printify/`, subscribe to the four order events. Use the signing secret stored in Heroku config vars.

11. **End-to-end test** — Place a real Stripe TEST order in test mode. Watch the logs:
    - Stripe webhook fires → Order created → submission to Printify called → printify_order_id stored
    - Order confirmation email queued → drained by mailer → arrives in your inbox
    - Wait for Printify to process the order in their dashboard (or use their test mode if available)
    - Trigger a manual webhook from Printify's dashboard if possible, or wait for production-state event
    - Status updates locally → shipped email arrives with tracking link

12. **Verify acceptance criteria** — Run through Sprint 4 acceptance criteria from the sprint plan.

## Critical reminders

- **Synchronous submission is intentional.** The order submission to Printify happens inside the Stripe webhook handler so failures are visible immediately. If you move this to a background task, you trade latency for observability — don't do that without a clear reason.
- **HMAC comparison must be timing-safe.** Use `hmac.compare_digest`, never `==`. Direct string comparison leaks timing information that can be used to forge signatures.
- **Idempotency in Printify webhooks too.** Same pattern as Stripe: WebhookEvent lookup before processing. Printify will replay webhooks on delivery failure.
- **Email DKIM/SPF/DMARC must pass before launch.** Use https://mail-tester.com or similar to verify. Without proper auth, emails land in spam, and customers won't get their order confirmations. This is a launch blocker.
- **Address validation matters here.** A bad shipping address is the most common Printify rejection. The Stripe Checkout collected address should be clean, but if Printify rejects it (validation in their API), the order ends up in `submission_failed` and the customer has paid but won't receive anything. Admin alert email exists for exactly this reason — handle these manually within hours of receipt, not days.
- **The customer paid before Printify confirmed.** This is by design — Stripe payment first, Printify submission second. If Printify rejects the order, you have a paid customer and no fulfillment. Manual intervention required: contact the customer, fix the address, resubmit. Document this workflow in the admin retry action.
- **Don't double-send emails on webhook replay.** The idempotency check prevents double-processing, but be especially careful with the email-sending side. Email log should be checked before sending, or the email function should be inside the WebhookEvent transaction.
- **Brand-aware everything.** Email templates render the brand's name, colors, support email. Never hardcode "Chesco" — use `order.brand.name`. Sprint 5 may introduce a second brand and your email templates must handle that.

## When to ask, when to act

**Just do** — anything in the sprint plan, anything mirroring HuntScrape's email patterns, anything covered by acceptance criteria.

**Ask first** — any decision about whether to send the "in production" email to customers (default: no, it's noise — only confirmation and shipped), any decision about retry intervals for failed Printify submissions (default: manual retry only, no automatic retry to avoid duplicate orders), any decision about Printify webhook events beyond the four specified (the others are mostly noise for v1).

**Push back if** — Printify's API rejects test orders in ways that suggest the order payload structure has changed from the docs (this happens), the webhook signature verification fails consistently (could be encoding issue or wrong secret), or the email deliverability is poor and DKIM/SPF setup is the actual blocker — flag that and stop before launch.

## Definition of done

Sprint 4 is complete when:

- All eight Sprint 4 deliverables from the sprint plan are met
- All six acceptance criteria pass
- A test order has been placed end-to-end and produced a real Printify order (still in test/Stripe-test mode is fine; live mode flip is Sprint 5)
- Order confirmation email arrived in inbox, passed DKIM/SPF/DMARC checks
- Forced webhook replay did not duplicate state changes or emails
- Code is on `main` in GitHub
- Sprint plan updated with any learnings about Printify webhook payload shape, email deliverability fixes, or fulfillment edge cases discovered
