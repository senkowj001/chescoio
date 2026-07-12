# Sprint 7 — Draft mode + one-click publish in ct-ops

> Handoff/context prompt for a fresh session. You have filesystem MCP read/write
> access to this repo (`C:\django\prod-django\chescoio`). Read the files named
> below before writing any code — do not assume, verify against the source.

## 0. Snapshot

- **Project:** `chesco.io` — "Chester County Apparel Co." A Django print-on-demand
  apparel storefront. Fulfillment via **Printify**, payments via **Stripe**.
- **Stack:** Django 5.x, PostgreSQL (Heroku `essential-0`), Heroku, gunicorn,
  HTMX, WhiteNoise. Split settings in `chescoio/settings/{base,production,local}.py`
  (`DJANGO_SETTINGS_MODULE=chescoio.settings.production` in prod).
- **Apps:** `brands`, `catalog`, `orders`, `core`. Django admin is mounted at
  **`/ct-ops/`**.
- **Deploy:** `git push heroku main` (Heroku builds a release, then dynos run it).
  One-off/shell: `heroku run -a chescoio "python manage.py <cmd>"` — note the
  **quotes around the whole command** or the Heroku CLI eats the flags.
- **Multi-brand-capable, currently one brand:** `Brand.domain = "chesco.io"`
  (bare apex), `printify_shop_id = 16351967`.

**Read these first (they define everything this sprint touches):**
- `catalog/models.py` — `Product.is_published` is `BooleanField(default=True)`;
  help text still says "Reflects Printify's visible flag." Module + field
  docstrings say products are pure caches mutated only by sync / admin read-only.
  **Both statements stop being true this sprint — update them.**
- `catalog/services.py` — `sync_brand_catalog()` / `_sync_one_product_inner()`.
  This is upsert-only and currently forces `'is_published': is_visible` where
  `is_visible = bool(data.get('visible', True))`. **This coupling is what we remove.**
- `catalog/admin.py` — `ProductAdmin` is fully read-only (`has_add_permission`
  and `has_delete_permission` return `False`; every field is in `readonly_fields`,
  including `is_published`). **We add publish/unpublish actions here.**
- `catalog/views.py` — `product_list` and `product_detail` both filter
  `is_published=True`. This is the storefront's visibility gate. **Leave as-is.**
- `catalog/management/commands/sync_printify_products.py` — the import command
  (verify its `--brand` flag / behavior).

## 1. What already shipped (do NOT redo)

The store just went live. Completed and confirmed working:
- **Stripe live cutover:** live `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` /
  `STRIPE_WEBHOOK_SECRET` set in Heroku. Live webhook endpoint at
  `https://www.chesco.io/webhooks/stripe/` subscribed to `checkout.session.completed`
  and `charge.refunded`. Stripe Tax product category set to **Clothing & Footwear**
  (physical apparel; PA/NJ clothing exemption). Account activation done.
- **Printify webhooks registered** via `register_printify_webhooks` at
  `https://www.chesco.io/webhooks/printify/` (7 topics). `PRINTIFY_WEBHOOK_SECRET`
  set in Heroku. The command was fixed this session to target the **www** host
  (see invariant below) — it's now `FORCE_WWW_DOMAINS`-aware.
- **Printify webhook payload bug fixed** in `orders/views.py`: `shop_id` is nested
  at `resource['data']['shop_id']` (an int), not top-level. Added `_printify_shop_id()`
  helper used by `_handle_printify_product_publish_started` and
  `_handle_printify_product_deleted`; added a `resource['data']` fallback to the
  shipment handler. **Deployed and confirmed live.**

## 2. Still open (context, not this sprint unless noted)

- **Real end-to-end test order** not yet run. When it is, capture the real
  `order:sent-to-production` and `order:shipment:created` payloads from
  `WebhookEvent` and confirm the order handlers read the order id / tracking from
  the right place — the order handlers were adjusted based on a *product* payload,
  so the shipment field shape is inferred, not verified.
- **Sync is upsert-only** — it never removes products that vanished from Printify.
  Deletions propagate only via the `product:deleted` webhook (sets
  `is_published=False`). A missed webhook orphans a row. A guarded
  "prune-missing" reconciliation was discussed and **deferred** (risk: a partial/empty
  Printify API response could hide the whole catalog — needs guards).

## 3. The Sprint 7 task

**Goal:** John wants real **draft mode** plus a **one-click publish** he controls
from ct-ops, instead of the site auto-publishing everything Printify returns.
The decision made: **`is_published` becomes a locally-owned field**, no longer a
mirror of Printify's `visible`. Printify's "Publish" button is abandoned entirely
(it only starts a channel handshake that locks the card and blocks editing — see
invariants). Workflow becomes:

1. Create/edit a design in Printify, leave it **Unpublished** there.
2. Import it into the local DB via sync — it lands as a **draft** (`is_published=False`, hidden).
3. In ct-ops, tick the design(s) and run **Publish** when ready → live on `/shop/`.

### Change A — decouple `is_published` from sync (`catalog/services.py`)

`_sync_one_product_inner()` must stop overwriting `is_published`. The subtlety:
`update_or_create(defaults=...)` applies `defaults` on **both** create and update,
and `Product.is_published` **defaults to `True`** on the model — so simply removing
it from `defaults` would make **new imports publish immediately** (model default),
which defeats draft mode.

Required behavior:
- **New products** import as **drafts** (`is_published=False`).
- **Existing products** keep whatever `is_published` John has set — sync must not touch it.

Preferred implementation (confirm Django ≥ 5.0 in `requirements.txt` first —
`create_defaults` needs 5.0+):
- Remove `is_published` from `defaults`.
- Add `create_defaults={'is_published': False}` (merged with `defaults`) so it's set
  **only on creation**.

If Django < 5.0: instead change the model default to `False` (+ migration) and remove
`is_published` from `defaults`. Update the field help text and the module docstring
either way (they currently claim it mirrors Printify / that admin is read-only).

Leave the `visible` read in place only if it's used elsewhere; otherwise drop the
now-dead `is_visible` line. Verify it isn't referenced for anything but `is_published`.

### Change B — publish/unpublish actions in ct-ops (`catalog/admin.py`)

Add two changelist actions to `ProductAdmin` (they appear in the actions bar at the
top of the Products page — this is the "button" John asked for):
- **"Publish (show on site)"** → `queryset.update(is_published=True)`
- **"Move to draft (hide)"** → `queryset.update(is_published=False)`

Notes:
- `.update()` writes `is_published` directly, so the field staying in `readonly_fields`
  (which only governs the change *form*) does **not** block these actions. Keep the rest
  of the admin read-only.
- Actions need change permission. The admin overrides `has_add`/`has_delete` to `False`
  but not `has_change_permission`, so a superuser has it — confirm actions render.
  If they don't, enable `has_change_permission` for the action to work without opening
  field editing.
- Give each action a clear `short_description` and a success message
  (`self.message_user(...)`) with the count.

### Change C — ops (John does these, not code)

- **Remove the nightly `sync_printify_products` Heroku Scheduler job** so nothing
  auto-publishes/auto-imports. Import becomes on-demand.
- Stop clicking **Publish** in the Printify UI.

## 4. Open decision to resolve with John

Import (pulling new Printify designs into the DB **as drafts**) currently runs via
the **"Sync Now" action on the Brand** in ct-ops. John hasn't decided whether to
**also** add a "Sync from Printify" button on the **Products** changelist so import
and publish live in one place. Ask before building the extra button; the Brand
"Sync Now" already covers import.

## 5. Invariants / gotchas (learned this session — respect them)

- **www, not apex, for webhooks.** `Brand.domain` is the bare apex `chesco.io`
  (`BrandMiddleware` strips `www.` before lookup). `ForceWwwRedirectMiddleware`
  301-redirects apex→www, and Printify/Stripe won't follow a redirect on a signed
  POST. Any webhook URL must be `https://www.chesco.io/...`.
- **Printify nests `shop_id` under `resource['data']`** (as an int). Use the
  `_printify_shop_id()` helper in `orders/views.py`.
- **Printify's `visible` flag ≠ channel-publish status.** It's "active product" and
  is `True` even for cards showing "Unpublished." Don't reintroduce a dependency on it.
- **Don't click "Publish" in Printify.** It locks the card ("Publishing…") pending a
  callback and blocks editing the design. The storefront is fed by sync, not the
  publish handshake. Stuck cards are cleared by calling `publishing_succeeded`
  (there's a shell loop over `PrintifyClient().list_products(...)` for this).
- **Printify has no sandbox** — every API order is real; it charges John's card/balance
  when sent to production (independent of Stripe payouts).
- **Admin is read-only by design** except for the two new actions.

## 6. Definition of done

- New Printify designs import as hidden drafts; existing published products stay
  published across syncs.
- `/shop/` shows only products John has explicitly published via the ct-ops action.
- Publish/unpublish actions work from the Products changelist with clear messaging.
- Docstrings/help text in `models.py` (and any comment in `services.py`) updated to
  reflect that `is_published` is locally owned, not a Printify mirror.
- Nightly sync job removed (John) so nothing publishes unattended.
