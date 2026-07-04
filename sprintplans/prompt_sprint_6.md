# Sprint 6 Implementation Prompt — Launch Recovery & Production Cutover

## Context — read this carefully before doing anything

Sprint 5 (legal/marketing pages, contact form, order lookup + tokenized status page, `charge.refunded` refund handling, SEO/OG/sitemap/robots, branded 404/500, and the Meta Pixel + Plausible analytics events) was fully implemented in code and committed. A brand **recolor** was then applied on top: titles/headings/wordmark → deep navy `#000052`, buttons/CTAs → blue `#0a6ed3`, delivered as a data migration `brands/0003_recolor_chesco.py` (it repoints the brand's `primary_color`/`accent_color`; buttons were repointed in templates from the primary token to the accent token). All of that is on `main` and was pushed to Heroku.

**The deploy did NOT go live.** Heroku's release phase runs `python manage.py migrate`, and it failed:

```
psycopg2.OperationalError: connection to server at
"c4fqkld51su0p3.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com" (3.219.12.110),
port 5432 failed: timeout expired
```

Heroku declares "this new release will not be available until the [release] command succeeds," so when the release-phase `migrate` failed, **the release (v29) was rolled back and Heroku is still serving the previous, pre-Sprint-5 build.** That is the whole reason the live site looks wrong:

- The wordmark/title is still green and the hero title is still charcoal (old code).
- The "Shop the collection" and other buttons are still **green** (old code).
- The "Coming Soon" kicker is still on the homepage (old code).
- There is no `/contact/` page live (Sprint 5 isn't live).

**Do not misread the green buttons as a code bug.** The button code is already correct: `templates/home.html` renders the CTA from `var(--color-brand-accent, #0a6ed3)`, every other button was repointed to `--color-brand-accent`, and `brands/0003_recolor_chesco.py` sets the brand's `accent_color` to `#0a6ed3`. Once the code is live and the migration is applied, the buttons are blue. **Do NOT re-edit button colors.** The only reason they are green is that the deploy hasn't gone live.

Local `runserver` works fine because dev uses SQLite; the failure is specifically the Heroku release dyno reaching Heroku Postgres, which says nothing about the code.

**Migration state on Heroku:** because the release-phase `migrate` never connected, *no* Sprint 5 migrations are applied in production. All of these are pending on Heroku:
- `core.0001_initial` (StaticPage, EmailSignup, ContactMessage)
- `core.0002_seed_static_pages` (seeds the six draft pages)
- `orders.0004_order_lookup_token_and_refunds` (lookup_token + refund fields)
- `brands.0003_recolor_chesco` (navy/blue recolor)

The master plan `eg_apparel_sprint_plan.md` (architecture, models, and the Sprint 5 delivery notes) is the source of truth — read it, and read the Sprint 5 delivery-notes section at the end of it, before starting.

The developer is John (East Goshen Technologies). Project at `C:\django\prod-django\chescoio\`. Direct recommendations preferred, honest pushback valued.

## Sprint 6 goal

Get the already-committed Sprint 5 + recolor code live (fix the release-phase DB failure and apply the migrations), then finish the actual launch: remove the "Coming Soon" placeholder, surface the (already-built) contact page, cut Stripe over to live mode, confirm transactional email actually sends and lands in the inbox, publish the legal pages, get real products live, wire the scheduled jobs, and work the launch checklist top-to-bottom.

This is primarily a **launch-execution and production-cutover** sprint. The code surface is small; most of the work is operational and must be run by John.

---

## Working environment & constraints (unchanged from Sprints 1–5)

- **Project:** module `chescoio`, root `C:\django\prod-django\chescoio\`, Heroku app `chescoio`. Django 5.2.12, PostgreSQL (prod) / SQLite (dev), Tailwind v4 browser CDN + HTMX, django-mailer, Stripe (currently test mode), Printify, **no Cloudflare** (Hostinger DNS).
- **Filesystem-only for Claude.** Edit the Windows project *only* via the `filesystem:*` MCP tools (`read_text_file`, `read_multiple_files`, `write_file`, `edit_file`, `create_directory`, `list_directory`, `directory_tree`). Container tools (str_replace/create_file/view/bash) do **not** operate on this project.
- **`filesystem:edit_file` is atomic per call:** every `oldText` in the call must match exactly or the whole call writes nothing. Match on lines without em-dashes where possible; some legacy Sprint 2/3 files contain literal `\uXXXX` escape sequences (e.g. `\u2014`, `\u2713`) rather than the real character — match accordingly. Use real UTF-8 characters in any new content.
- **bash / network are DISABLED for Claude.** Claude cannot run `manage.py`, `migrate`, `pip`, `heroku`, `stripe`, Printify calls, or DNS. **John runs all of those.** Migrations are **hand-written** to match the existing convention; John runs `makemigrations --check` (expect "no changes") and `migrate`.
- **Multiline template comments must use `{% comment %}…{% endcomment %}`.** A multi-line `{# … #}` leaks into the rendered page (this bit us three times in Sprint 3).
- **Brand colors live in the DB.** `base.html` sources `--color-brand-primary` / `--color-brand-accent` from the `Brand` row (`primary_color`/`accent_color`); do not hardcode brand colors in `base.html`. Headings/wordmark/text-links use primary (navy); buttons use accent (blue).
- **Division of labor for this sprint:** Claude makes the small code/doc changes via MCP (remove Coming Soon, header nav link, `.python-version`, optional DB-connection hardening, any migration, sprint-plan delivery notes). **John executes every operational step** (Heroku, Stripe, Printify, DNS, Plausible/Meta, mail-tester, Search Console, placing real orders). Each step below is tagged **[John]**, **[Claude]**, or **[John+Claude]**.

---

## Pre-work (do first, in order)

1. **[John] Confirm database reachability right now.** Run `heroku run python manage.py showmigrations` (or `heroku pg:info`). This one command tells us whether the release failure was a transient blip (most likely) or an ongoing connectivity problem — and it drives Workstream A below. Do this before any code work; if the DB is unreachable, nothing else can deploy.
2. **[Claude] Re-read** `eg_apparel_sprint_plan.md` (esp. the launch checklist and the Sprint 5 delivery notes) and skim the Sprint 5 code that is about to go live (`core/`, the new `orders/` refund + lookup views, the templates). You are shipping code that was written but never run in production — know what it does.
3. **[John] Decide launch posture:** soft launch (you + a few trusted buyers) before any public announcement. Confirm you're not announcing publicly until the checklist is fully verified. Don't launch on a Friday.
4. **[John] Confirm the prerequisites that gate real orders exist:** Stripe account fully activated (business details + bank), Printify billing/payment method set (Printify charges you per fulfillment), and at least a handful of real products ready to publish. If any of these isn't ready, that part of the sprint waits.

---

## Workstream A — Unblock the deploy (CRITICAL, do first, blocks everything)

Nothing else in this sprint can go live until the release succeeds. The traceback shows `migrate` failing at the *initial connection* (it dies in `ensure_connection()` before running any migration), so this is DB reachability, not a bad migration.

1. **[John] Try the migration manually:** `heroku run python manage.py migrate`.
   - **If it succeeds:** the earlier failure was transient. The migrations are now applied — but the *code* (v29) is still not live because that release rolled back. Re-trigger a release to activate the code: `git commit --allow-empty -m "Re-trigger release" && git push heroku main` (the release-phase `migrate` will now be a no-op and should succeed). Then jump to step 4.
   - **If it times out again:** it's not transient — continue to step 2.
2. **[John] Diagnose the Postgres instance / platform:**
   - `heroku pg:info` — check status, connection count, and row count (Essential-0 has a ~10,000-row limit and ~20-connection limit; verify you're under both).
   - `heroku pg:diagnose` — surfaces connection, bloat, and limit issues.
   - Check `status.heroku.com` and the Heroku Postgres dashboard for a maintenance window or incident on `us-east-1`.
   - Confirm `DATABASE_URL` is present and current: `heroku config:get DATABASE_URL` (it should match the RDS host in the error; if credentials were rotated, `heroku pg:credentials:url` / re-attaching resolves a stale URL).
3. **[Claude, optional hardening] Make the DB connection fail fast and cleanly** in `chescoio/settings/production.py`: add a `connect_timeout` (e.g. 10s) to the Postgres `OPTIONS` so a hung connect surfaces quickly instead of hanging the release, and confirm `CONN_HEALTH_CHECKS = True` and `conn_max_age = 60` are still set (Sprint 3 lowered `conn_max_age` from 600 to 60 for exactly this class of idle-reap problem). If the timeout recurs under load, recommend John upgrade the Postgres plan (Essential-0 → Essential-1/Standard-0) for headroom — note it, don't assume it.
4. **[John] Verify the code is actually live** once the release succeeds: load `https://www.chesco.io` and confirm the wordmark is navy, buttons are **blue**, `/contact/` resolves, `/privacy/` behaves (it should 404 for the public until published — see Workstream F), and `/robots.txt` + `/sitemap.xml` return. Also confirm `heroku run python manage.py showmigrations` shows `core`, `orders.0004`, and `brands.0003` all applied.

Acceptance for A: release succeeds, all four pending migrations applied in production, and the live site shows the navy/blue recolor.

---

## Workstream B — Front-end fixes (small, [Claude] edits; go live via the next deploy)

1. **Remove the "Coming Soon" placeholder** in `templates/home.html`:
   - Change the title block `{% block title %}{{ request.brand.name }} — Coming Soon{% endblock %}` to a real title (e.g. `{% block title %}{{ request.brand.name }} — {{ request.brand.tagline }}{% endblock %}`).
   - Remove (or replace with something launch-appropriate, or gate behind a flag) the kicker `<p class="text-xs uppercase tracking-[0.2em] text-neutral-500 mb-6">Coming Soon</p>`. If John wants a kicker, use something like the tagline; otherwise delete the paragraph. Confirm the copy with John.
   - Note: the accent hairline at the bottom of `home.html` still has a stale amber fallback `var(--color-brand-accent, #f4a261)`; harmless (the DB var is blue), but you may normalize it to `#0a6ed3` while you're in the file.
2. **Add a "Contact" link to the header nav.** `templates/partials/header.html` currently has only "Shop" + the mini-cart. Add a `Contact` link (`{% url 'core:contact' %}`) alongside "Shop" so the contact page is reachable from every page, not just the footer. (The contact page itself already exists — see C.)
3. **Do NOT touch button colors.** They are already correct (accent token). Verify visually after deploy instead.

---

## Workstream C — Contact page (already built in Sprint 5; verify + surface)

The contact page John asked for **already exists** and ships with the Sprint 5 code: route `core:contact` at `/contact/`, view `core.views.contact` (GET/POST, honeypot field named `company`), `templates/core/contact.html` + `_contact_form.html` + `_contact_success.html`, and a `ContactMessage` audit model. It just isn't live yet (Workstream A) and wasn't linked in the header (Workstream B).

1. **[John] After deploy, test it end-to-end:** submit the form, confirm you land on the success fragment, confirm a `ContactMessage` row is created in admin, and confirm the notification email is actually delivered to `brand.support_email` (this depends on Workstream D-email being real, not console). If the email doesn't arrive, that's an email-backend problem, not a form problem.
2. **[Claude, if John wants] Minor polish only** (e.g. header link done in B, a short intro line). Don't rebuild it.

---

## Workstream D — Transactional email actually sends (likely the biggest hidden gap)

The app queues mail through django-mailer (`EMAIL_BACKEND = 'mailer.backend.DbBackend'`), which writes to a DB queue that must be **drained by a separate process**, and the drain relies on a real SMTP backend being configured behind mailer. In dev this is the console backend, so nothing has actually been sent. Confirm the production path is real before launch.

1. **[John] Confirm a production email provider is configured.** Verify `MAILER_EMAIL_BACKEND` (the backend mailer hands off to) points at a real SMTP/API provider (SendGrid, Mailgun, Postmark, or AWS SES) and that the provider credentials are set in Heroku config. If none is set, mail is not being sent at all — set one up. `DEFAULT_FROM_EMAIL` is `hello@chesco.io`.
2. **[John] Set up sender authentication DNS for chesco.io:** SPF, DKIM, and DMARC records at Hostinger for the chosen provider. This is a **launch blocker** — without it, confirmation/shipped emails land in spam.
3. **[John+Claude] Ensure the queue is drained on a schedule.** django-mailer needs `python manage.py send_mail` run frequently (e.g. every 10 minutes) and `python manage.py retry_deferred` periodically. Add these as Heroku Scheduler jobs (see Workstream E's scheduler note; Claude can document the exact commands, John adds the jobs). Without a drain job, queued emails never leave.
4. **[John] Verify deliverability with mail-tester.com** for the order-confirmation, shipped, and contact emails — target **≥ 9/10**, DKIM/SPF/DMARC all passing. Send yourself a real confirmation (place a test order) and a real contact submission and confirm inbox delivery.

---

## Workstream E — Products, catalog, and scheduled jobs

1. **[John] Get real products live.** Confirm `Brand.printify_shop_id` is set (seed baked it in), then sync + publish: `heroku run python manage.py sync_printify_products --brand=chesco.io`, and make sure the products are published (visible) in Printify so they sync as `is_published=True`. The storefront shows an empty state until products exist. Verify product list, product detail, variant selection, images, and the size guide render.
2. **[John+Claude] Wire the Heroku Scheduler jobs** the earlier sprints deferred to launch (Claude documents exact commands/frequencies; John adds them in `heroku addons:open scheduler`):
   - `python manage.py sync_printify_products --brand=chesco.io` — hourly (product sync; publish webhooks cover near-instant, this is the safety net).
   - `python manage.py send_mail` — every 10 minutes (drain mailer queue; from Workstream D).
   - `python manage.py retry_deferred` — hourly (retry failed emails).
   - `python manage.py clear_old_carts` — daily (cart cleanup; command shipped in Sprint 3).
3. **[John] Register the Printify webhook** if not already: `heroku run python manage.py register_printify_webhooks --brand=chesco.io` (order + product events), endpoint `https://www.chesco.io/webhooks/printify/`.

---

## Workstream F — Stripe production cutover (the core launch gate)

Currently in **test mode**. Live mode is a one-way door for testing: real charges. Use your own card for the first live order and refund yourself; do not use a friend's card (fee artifacts + risk-team flags).

1. **[John] Activate the Stripe account** for live payments (business details + bank) if not already done.
2. **[John] Configure Stripe Tax in LIVE mode.** Test-mode tax settings do not automatically carry to live. Re-verify in live: head-office address set, PA tax registration active, and the **default product tax code set to `txcd_30011000` (Clothing & Footwear)** — this is critical. Sprint 3 burned a lot of time because a "shortest-name" heuristic picked `txcd_30011201 Fur Clothing` (fur is a PA exemption *exception*), so PA clothing was taxed. Hardcode `txcd_30011000`; there's a `configure_stripe_*.py` script pattern from Sprint 3 you can adapt for live, or set it in the dashboard. Confirm PA clothing computes **$0.00 tax** in a live tax preview.
3. **[John] Flip the keys:** set the live `STRIPE_SECRET_KEY` (`sk_live_…`) and publishable key (`pk_live_…`) in Heroku config. Keep test keys in dev only.
4. **[John] Register the LIVE webhook endpoint** in the Stripe dashboard: `https://www.chesco.io/webhooks/stripe/`, subscribed to **both `checkout.session.completed` and `charge.refunded`** (the refund handler is new in Sprint 5). Set the endpoint's **live signing secret** as `STRIPE_WEBHOOK_SECRET` in Heroku config. Redeploy so the config is picked up.
5. **[John] Confirm Printify billing** is set up (a real payment method) so live orders actually fulfill rather than erroring at submission.
6. **[John] First real end-to-end order:** your own card, real address, real Printify fulfillment. Watch the whole pipeline: live charge → `checkout.session.completed` webhook → Order created → Printify submission → confirmation email → (later) shipped email with tracking. Document anything that breaks.
7. **[John] Real refund test:** issue a refund (try a partial) from the Stripe dashboard and confirm the `charge.refunded` webhook updates the Order — `refunded_cents`/`refunded_at` populated, status → `refunded` only on a full refund. Remember: Printify does **not** auto-refund fulfillment cost; that's a separate Printify support ticket (the admin Refunds panel notes this).

---

## Workstream G — Analytics, SEO, and launch hygiene

1. **[John] Stand up analytics and set the brand fields.** The events (`ViewContent`, `AddToCart`, `InitiateCheckout`, `Purchase` with a Meta dedup `eventID`) are coded but only fire when the brand has them configured. Create a Plausible site for `chesco.io` and a Meta Pixel, then set `Brand.plausible_domain` and `Brand.meta_pixel_id` (admin, or a small data migration — [Claude] can write the migration if John prefers that over admin). **[John] Verify** each event fires with the Meta Pixel Helper + Plausible debug, including `Purchase` with the correct value on the receipt.
2. **[John] Review and publish the legal pages.** privacy, terms, returns, and shipping ship as staff-only drafts (`is_published=False`, `needs_review=True`); about + size-guide ship published. In admin, review/edit each draft (**do not launch without returns and privacy approved**), uncheck `needs_review`, and publish. The footer links appear automatically once published; the public 404s on them until then.
3. **[John] SEO surface:** after deploy, fetch `https://www.chesco.io/robots.txt` and `/sitemap.xml` to confirm they return, then submit the sitemap in Google Search Console. Set `Brand.logo_url` to a real 1200×630 OG image (OG/Twitter tags reference it) and confirm a favicon exists.
4. **[Claude] Replace the deprecated `runtime.txt`.** The build warns that `runtime.txt` is deprecated and that pinning the patch (`python-3.12.8`) blocks security updates. Create a `.python-version` file at the project root containing exactly `3.12` (major only, no `python-` prefix, no patch) and have John delete `runtime.txt`.
5. **[John] Secrets hygiene (pending since Sprint 3):** rotate the test-mode Stripe keys and the Printify PAT that were pasted into chat during earlier dev, and update `.env` + Heroku. Delete the Sprint 3 test Order #1 artifact if it's still in prod.
6. **[John] Backups:** confirm `heroku pg:backups:capture` runs clean and a backup schedule is set.
7. **[John, optional] Stack upgrade:** Heroku-24 → Heroku-26 is available; defer unless convenient (don't do it in the same change as launch).

---

## Critical reminders

- **The deploy is the blocker, not the button code.** Workstream A comes first; do not spend time "fixing" green buttons in the templates — they are correct and will be blue once live.
- **Email deliverability (DKIM/SPF/DMARC) and a working drain job are launch blockers.** Confirm real send + inbox delivery before announcing.
- **PA clothing must compute $0.00 tax in live mode.** Hardcode `txcd_30011000`; verify in a live tax preview.
- **Register `charge.refunded` on the live webhook**, not just `checkout.session.completed` — the refund handler is new and won't fire otherwise.
- **Acceptance is binary.** Check a launch-checklist item only after you've tested it live, not because it "should work."
- **Soft launch, then announce.** Place your own order, have 2–3 trusted people order, fix what surfaces, then go public. Not on a Friday.
- **2.0 stays deferred** (photography, Etsy, abandoned cart, B2B intake, second brand). Note, don't build.

## When to ask, when to act

- **Just do:** the deploy-recovery code hardening, removing "Coming Soon," the header contact link, `.python-version`, any hand-written migration, documenting scheduler commands, and sprint-plan updates.
- **Ask John first:** the exact homepage kicker/headline copy replacing "Coming Soon," any legal policy language (John owns the substance), launch timing and which channels to announce on, pricing/promo decisions, and whether to upgrade the Postgres plan or Heroku stack.
- **Push back if:** a launch-checklist item is "mostly working" rather than verified; DKIM/SPF/DMARC aren't passing; live-mode PA clothing is taxed; the live webhook is missing `charge.refunded`; or any production smoke test fails.

## Definition of done

- The release succeeds and all four pending migrations are applied in production; the live site shows the navy/blue recolor, no "Coming Soon," a reachable/working contact page, and blue buttons.
- Stripe is live: one real personal order placed, fulfilled by Printify, received; one real refund processed end-to-end; PA clothing taxed at $0.00.
- Transactional email sends for real and passes mail-tester ≥ 9/10 with DKIM/SPF/DMARC.
- Products are synced and published; the storefront is populated.
- Scheduler jobs (product sync, mail drain, retry_deferred, cart cleanup) are running.
- Analytics events verified firing; legal pages reviewed and published; robots.txt/sitemap.xml fetch and sitemap submitted to Search Console.
- `.python-version` replaces `runtime.txt`; test-mode secrets rotated; backups confirmed.
- Code on `main` in GitHub; a **"Sprint 6 — delivery notes"** section is appended to `eg_apparel_sprint_plan.md` documenting what was done, the deploy root-cause/fix, and any deviations (follow the same delivery-notes convention as Sprints 1–5).

After launch: the next 1–2 weeks are operational — watch the support inbox and logs, fulfill the first orders manually-monitored, then begin the 2.0 priorities (starting with the B2B intake form, the actual revenue lane).
