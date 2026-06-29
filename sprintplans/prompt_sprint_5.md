# Sprint 5 Implementation Prompt — Polish, Legal, SEO & Launch

## Context

You are implementing Sprint 5 of the East Goshen Apparel Platform — the final sprint before launch. Sprints 1-4 are complete: full e-commerce pipeline working in Stripe test mode, Printify orders being submitted and tracked, transactional emails firing. The full sprint plan is in `eg_apparel_sprint_plan.md` — read it before starting.

The developer is John (East Goshen Technologies). Project at `C:\django\prod-django\eg_apparel\`. Filesystem MCP workflow, direct recommendations preferred, honest pushback valued.

## Sprint 5 goal

Take the platform from "works in test mode" to "open for business." Legal pages drafted, SEO basics in place, public-facing polish applied, Stripe flipped to live mode, a real personal order placed and received, and the launch checklist completed top-to-bottom.

## Pre-work (do this first, in order)

1. Read the full sprint plan, focusing on "Sprint 5" and the launch checklist
2. Read HuntScrape's privacy policy, terms of service, and returns policy pages — these are the patterns to adapt, not copy. Apparel has different terms than SaaS.
3. Confirm with John: the legal pages need his sign-off on substance (not just structure) — flag this early so he can write or approve the actual policy text rather than you guessing at it
4. Confirm: the brand voice for chesco.io ("Made for the 610." was the tagline) — about page and product copy need to reflect this. Ask John for the voice and a few sample phrases if not already documented.
5. Identify the OpenGraph image dimensions needed (1200x630 recommended) and whether a generic brand OG image exists yet — if not, this needs to be created in Canva or similar before launch
6. Verify Stripe Tax is fully registered for PA before any live-mode testing

## Implementation order

Work in this sequence and commit after each step:

1. **Legal pages scaffolding** — Create routes for `/privacy/`, `/terms/`, `/returns/`, `/shipping/`, `/contact/`, `/about/`, `/size-guide/`. Use a `legal_page` template that renders markdown content from the database (a simple `StaticPage` model with brand + slug + title + content fields) so John can edit copy without redeploying. Brand-scoped so future brands have their own legal pages.

2. **Legal page content** — Hand the drafts to John for review/edits, do not just generate and ship. He needs to own the substance, especially around:
   - Returns policy (final sale except defects, 14-day window from delivery)
   - Terms (governing law = Pennsylvania, arbitration clause optional, DMCA contact)
   - Privacy (Stripe, Printify, Plausible, Meta Pixel, email signups — each disclosed)
   - Shipping (Printify-fulfilled, US-only for v1, estimated 5-10 business days)

3. **About / Story page** — John writes the copy; you build the template. Brand-aware so it reads from a `Brand.about_content` field (add the field via migration) or a StaticPage. Should feel like a person made this, not a dropshipper.

4. **Contact form** — Simple form (name, email, message), validates, submits via HTMX, sends to `request.brand.support_email`, logs to a `ContactMessage` model for audit. Include honeypot field for spam (mirror HuntScrape).

5. **SEO meta tags** — Update `base.html` with full OpenGraph + Twitter Card + standard meta tags. Per-page overrides via template blocks. Product detail pages override `og_image` to the product's default image, `og_title` to the product title, `og_description` to a truncated description.

6. **robots.txt and sitemap.xml** — Dynamic views, brand-aware. `robots.txt` allows all, points at sitemap. `sitemap.xml` includes homepage, shop list, all published products, all legal pages. Use Django's built-in `sitemaps` framework.

7. **Email signup form** — `EmailSignup` model with brand FK, email, source (footer / homepage / popup), created_at, is_confirmed (false for v1, no double opt-in until 2.0). Footer form on every page. Posts via HTMX, returns thank-you fragment.

8. **Order lookup page** — `/orders/lookup/` form with email + order ID. On match, redirect to a public order detail page showing status, items, tracking. The order ID itself is the auth — long random IDs prevent enumeration. Generate `Order.lookup_token` (random 32-char string) on order creation and use it as the URL path component instead of the integer ID for safety. Migration required.

9. **404 and 500 pages** — Branded error templates. The brand-not-found 404 from Sprint 1 stays as-is for unknown hostnames; the generic 404 (page not found within a valid brand) uses the brand's theme. 500 page is brand-aware too.

10. **Cloudflare WAF rules** — Mirror HuntScrape's WAF configuration: block known bad UAs, rate-limit `/webhooks/` to reasonable thresholds (Stripe and Printify webhooks are infrequent), rate-limit `/contact/` and form endpoints to prevent abuse. Bot Fight Mode on. Verify legitimate traffic isn't blocked.

11. **Plausible and Meta Pixel verification** — Use Plausible's debug mode and Meta's Pixel Helper browser extension to confirm events are firing on key pages: page views, product detail views, add-to-cart, initiate-checkout, purchase. Purchase event should fire on the success page with the correct value.

12. **Stripe live mode flip** — In Stripe dashboard, switch to live mode. Generate new live API keys, update Heroku config. Register the production webhook endpoint with the new live webhook signing secret. Update env vars. Redeploy. The test mode keys stay in dev/staging.

13. **First real end-to-end order** — Place a real order with your own card, real shipping address, real Printify fulfillment. Watch the entire pipeline: Stripe live charge → webhook → Order → Printify submission → emails → wait for shipment → tracking → delivery. Document any issues found. This is the gate before public launch.

14. **Refund flow test** — Issue a partial refund through Stripe dashboard for the test order. Verify the Order status updates correctly via the `charge.refunded` webhook (you may need to add this handler if Sprint 3 didn't cover it). Refunds in Printify happen separately and require a support ticket — document this in the admin retry workflow.

15. **Launch checklist** — Work through every item in the sprint plan's launch checklist. Each item gets checked off only when verified working. Do not check items off based on "should work" — only on "I just tested it and confirmed."

16. **Verify acceptance criteria** — Run through all Sprint 5 acceptance criteria.

## Critical reminders

- **Live mode is a one-way door for testing.** Once you charge a real card, that's a real charge. Use your own card for the first live test. Refund yourself. Do not use a friend's card or a test purchase that gets refunded — it generates fee artifacts and looks suspicious to Stripe's risk team.
- **Legal copy is the developer's lowest-leverage work.** Don't write privacy policies from scratch. Use a template (Termly, iubenda, or fork from HuntScrape) and adapt. John signs off on the final language. Do not ship without his explicit approval on returns and privacy specifically.
- **DKIM/SPF/DMARC verification is a launch blocker.** If transactional emails are landing in spam, customers won't see their confirmations and you'll get angry support emails. Verify before announcing launch.
- **The first 48 hours post-launch are watch-dog time.** Sit on the support inbox, watch the logs, check every order manually. Sprint 5 isn't truly done until you've successfully fulfilled 3-5 real orders without manual intervention.
- **Don't launch on a Friday.** If you launch Friday afternoon, the first weekend's issues hit you with no support available from Stripe, Printify, or Heroku until Monday. Launch Tuesday or Wednesday morning. Boring but real.
- **Soft launch before announcement.** Make the site live, place your own order, ask 2-3 people you trust to place orders. Fix issues found. Then announce publicly. Avoid the public discovering bugs you could have found in 48 hours of quiet.
- **2.0 list is not Sprint 5.** Resist scope creep into things on the deferred list (photography, Etsy channel, abandoned cart, B2B form, second brand). Note them, defer them, ship.

## When to ask, when to act

**Just do** — anything in the sprint plan, anything mirroring existing East Goshen patterns, anything covered by acceptance criteria.

**Ask first** — any legal policy language (John writes/approves the substance), any decision about whether to launch to public or stay in soft launch longer, any decision about pricing strategy or promotional codes for launch, any decision about which channels to announce on first.

**Push back if** — the launch checklist has items that are "mostly working" rather than verified (do not let this slip), DKIM/SPF/DMARC aren't passing cleanly (do not launch), Stripe Tax is calculating PA clothing as taxable (configuration issue, must fix before launch), or any production smoke test fails (do not promote to live mode).

## Definition of done

Sprint 5 — and the v1 build — is complete when:

- All thirteen Sprint 5 deliverables from the sprint plan are met
- Every item on the launch checklist is verified and checked off
- One real personal order has been placed in live Stripe mode, fulfilled by Printify, and received in the mail
- A real refund has been processed end-to-end without issues
- Email deliverability passes mail-tester.com with 9/10 or better
- Cloudflare WAF is active without blocking legitimate traffic
- The 2.0 deferred list is documented in the sprint plan with priority order
- John has approved all customer-facing copy (legal, about, product descriptions for at least the first 5-10 designs)
- Code is on `main` in GitHub
- Sprint plan document is updated with final launch state, known limitations, and the prioritized 2.0 roadmap

After launch, the next 2-week period is operational: monitor orders, drain support inbox, fix bugs found in the wild, and begin work on the 2.0 priorities (likely starting with B2B order intake form since that's the actual revenue lane).
