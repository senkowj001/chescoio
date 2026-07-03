"""
Configure Stripe (test mode) for chescoio Sprint 3 development.

This script is the "ask Claude to set up Stripe via the API" workflow for
the claude.ai web chat surface, which doesn't have a native Stripe MCP
connector — Claude writes the script, you run it once.

What it does (in order, all idempotent):
  1. Verify STRIPE_SECRET_KEY in .env is a working test-mode key
  2. Set the head office address on the account (required before tax
     registrations can be created). If one is already set, leaves it alone.
  3. Set a default product tax code on tax settings (required when
     automatic_tax is enabled at checkout and individual line items
     don't carry their own tax_code). Picks a clothing-category code
     dynamically from stripe.TaxCode.list() so PA's clothing exemption
     fires correctly. Also sets tax_behavior=exclusive to match our
     checkout line items.
  4. List existing Stripe Tax registrations on the account
  5. Add a Pennsylvania state_sales_tax registration if missing
     (required for the PA clothing-exemption acceptance criterion)
  6. List existing webhook endpoints (informational — production endpoint
     gets registered in Sprint 5; dev uses `stripe listen`)

Safe to re-run. Refuses to run against a non-test key (sk_live_...).

Head office address defaults to a generic West Chester, PA location.
Override via these optional .env values if you want a different address:
    STRIPE_HEAD_OFFICE_COUNTRY     (default: US)
    STRIPE_HEAD_OFFICE_STATE       (default: PA)
    STRIPE_HEAD_OFFICE_CITY        (default: West Chester)
    STRIPE_HEAD_OFFICE_POSTAL_CODE (default: 19380)
    STRIPE_HEAD_OFFICE_LINE1       (default: blank \u2014 Stripe accepts
                                    country+state+city+ZIP without a street)

Usage:
    python scripts/configure_stripe_dev.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Load .env without dragging in Django settings — this script doesn't need them.
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

import stripe  # noqa: E402


# =============================================================================
# Helpers
# =============================================================================

def banner(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def bail(msg: str, code: int = 1) -> None:
    print(f"\n[abort] {msg}", file=sys.stderr)
    sys.exit(code)


def get_attr_or_key(obj, name, default=None):
    """Access StripeObject fields by attribute OR dict get \u2014 v15+ no longer
    inherits from dict, so .get() may not exist on some sub-objects."""
    if obj is None:
        return default
    if hasattr(obj, name):
        return getattr(obj, name, default)
    if hasattr(obj, "get"):
        return obj.get(name, default)
    return default


# =============================================================================
# 0. Pre-flight
# =============================================================================

api_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
if not api_key:
    bail("STRIPE_SECRET_KEY is not set in .env. Add it before running this script.")
if not api_key.startswith("sk_test_"):
    bail(
        "Refusing to run against a non-test key. This script is dev-only.\n"
        "Production webhook + registration setup belongs in Sprint 5 with extra care."
    )

stripe.api_key = api_key


# =============================================================================
# 1. Verify account
# =============================================================================

banner("1. Verify Stripe account")

try:
    account = stripe.Account.retrieve()
except stripe.error.AuthenticationError as e:
    bail(f"Stripe rejected the API key: {e}")
except stripe.error.StripeError as e:
    bail(f"Could not retrieve account: {e}")

print(f"  account_id          : {account.id}")
print(f"  country             : {account.country}")
print(f"  default_currency    : {account.default_currency}")
print(f"  charges_enabled     : {account.charges_enabled}")
print(f"  livemode (from key) : False  (sk_test_* prefix)")


# =============================================================================
# 2. Head office address (required before tax registrations)
# =============================================================================

banner("2. Head office address (tax settings)")

try:
    settings = stripe.tax.Settings.retrieve()
except stripe.error.StripeError as e:
    bail(f"Could not retrieve tax settings: {e}")

existing_address = get_attr_or_key(get_attr_or_key(settings, "head_office"), "address")
existing_country = get_attr_or_key(existing_address, "country")

if existing_country:
    state = get_attr_or_key(existing_address, "state") or ""
    city = get_attr_or_key(existing_address, "city") or ""
    postal_code = get_attr_or_key(existing_address, "postal_code") or ""
    line1 = get_attr_or_key(existing_address, "line1") or ""
    print(f"  Head office already set:")
    print(f"    country     : {existing_country}")
    print(f"    state       : {state}")
    print(f"    city        : {city}")
    print(f"    postal_code : {postal_code}")
    print(f"    line1       : {line1 or '(not set)'}")
    print("  Leaving as-is (will not overwrite). Re-run after editing in")
    print("  the dashboard if you change the head office.")
else:
    country = os.environ.get("STRIPE_HEAD_OFFICE_COUNTRY", "US")
    state = os.environ.get("STRIPE_HEAD_OFFICE_STATE", "PA")
    city = os.environ.get("STRIPE_HEAD_OFFICE_CITY", "West Chester")
    postal_code = os.environ.get("STRIPE_HEAD_OFFICE_POSTAL_CODE", "19380")
    line1 = os.environ.get("STRIPE_HEAD_OFFICE_LINE1", "").strip()

    address: dict = {
        "country": country,
        "state": state,
        "city": city,
        "postal_code": postal_code,
    }
    if line1:
        address["line1"] = line1

    print(f"  Setting head office to:")
    for k, v in address.items():
        print(f"    {k:<11} : {v}")

    try:
        settings = stripe.tax.Settings.modify(head_office={"address": address})
    except stripe.error.StripeError as e:
        bail(
            f"Could not set head office address: {e}\n"
            f"If this is a state/postal validation issue, set\n"
            f"STRIPE_HEAD_OFFICE_LINE1 in .env to a street address and re-run."
        )
    print(f"  Tax settings status: {settings.status}")


# =============================================================================
# 3. Default product tax code (preset PTC) on tax settings
# =============================================================================

banner("3. Default product tax code (preset PTC)")

# Optional CLI override — pass --force-code=txcd_XXXXXXX to change the
# currently-set default. Useful when the initial dynamic pick turns out to
# be a specialty subcategory (e.g. athletic apparel, which PA still taxes)
# instead of the plain "General - Clothing" code we want for chesco.io.
force_code = None
for arg in sys.argv[1:]:
    if arg.startswith("--force-code="):
        force_code = arg.split("=", 1)[1].strip()

existing_defaults = get_attr_or_key(settings, "defaults")
existing_default_code = get_attr_or_key(existing_defaults, "tax_code")
existing_default_behavior = get_attr_or_key(existing_defaults, "tax_behavior")

print(f"  Current default tax_code : {existing_default_code or '(not set)'}")
print(f"  Current default behavior : {existing_default_behavior or '(not set)'}")

# Always list clothing-adjacent candidates for diagnostic value — even when
# a default is already set, seeing the full menu of options makes it obvious
# whether we picked the right one and, if not, what to switch to.
print()
print("  Clothing-category codes available in Stripe's catalog:")
clothing_candidates = []
try:
    for tc in stripe.TaxCode.list(limit=100).auto_paging_iter():
        name = (tc.name or "").lower()
        description = (tc.description or "").lower()
        if (
            "clothing" in name
            or "apparel" in name
            or "footwear" in name
            or ("clothing" in description and "general" in name)
        ):
            clothing_candidates.append(tc)
except stripe.error.StripeError as e:
    bail(f"Could not list tax codes: {e}")

if not clothing_candidates:
    bail(
        "No clothing-category tax codes found in Stripe's catalog. This\n"
        "is unexpected; Stripe Tax should always have a 'General Clothing'\n"
        "or similar code available."
    )

clothing_candidates.sort(key=lambda t: (len(t.name or ""), t.name or ""))
for tc in clothing_candidates[:20]:
    marker = "  * " if tc.id == existing_default_code else "    "
    print(f"{marker}{tc.id}  {tc.name}")
if len(clothing_candidates) > 20:
    print(f"     ... and {len(clothing_candidates) - 20} more")
print()
print("  (* = currently set as default)")

# Decide what to do:
#   - If --force-code was passed: unconditionally set that code as default
#   - Elif no default is set: pick the shortest-named clothing candidate
#   - Else: leave existing default alone (idempotent re-run)
target_code = None
if force_code:
    target_code = force_code
    print(f"\n  --force-code={force_code} — will overwrite current default.")
elif not existing_default_code:
    target_code = clothing_candidates[0].id
    print(f"\n  No default currently set; will use {target_code}.")
else:
    print("\n  Default already set; leaving as-is.")
    print("  To change, re-run with --force-code=txcd_XXXXXXX.")

if target_code:
    try:
        settings = stripe.tax.Settings.modify(
            defaults={
                "tax_code": target_code,
                "tax_behavior": "exclusive",
            }
        )
    except stripe.error.StripeError as e:
        bail(f"Could not set default tax code: {e}")
    print(f"  Set defaults.tax_code={target_code}, defaults.tax_behavior=exclusive")
    print(f"  Tax settings status: {settings.status}")


# =============================================================================
# 4. List existing tax registrations
# =============================================================================

banner("4. Existing Stripe Tax registrations")

try:
    registrations = stripe.tax.Registration.list(limit=100)
except stripe.error.StripeError as e:
    bail(f"Could not list tax registrations: {e}")

if not registrations.data:
    print("  (none on this account yet)")
else:
    for r in registrations.data:
        country_block = get_attr_or_key(r.country_options, r.country.lower())
        state = get_attr_or_key(country_block, "state", "")
        reg_type = get_attr_or_key(country_block, "type", "")
        loc = f"{r.country}" + (f"/{state}" if state else "")
        print(f"  {r.id}  {loc:<10}  type={reg_type or '(n/a)'}  status={r.status}")


# =============================================================================
# 5. Register Pennsylvania if missing
# =============================================================================

banner("5. Pennsylvania (state_sales_tax)")


def _has_active_us_state(regs, state_code: str, reg_type: str) -> bool:
    for r in regs:
        if r.country != "US" or r.status != "active":
            continue
        us = get_attr_or_key(r.country_options, "us")
        if us is None:
            continue
        if (
            get_attr_or_key(us, "state") == state_code
            and get_attr_or_key(us, "type") == reg_type
        ):
            return True
    return False


if _has_active_us_state(registrations.data, "PA", "state_sales_tax"):
    print("  PA state_sales_tax already active \u2014 nothing to do.")
else:
    print("  Creating PA state_sales_tax registration (test mode)...")
    try:
        new_reg = stripe.tax.Registration.create(
            country="US",
            country_options={"us": {"state": "PA", "type": "state_sales_tax"}},
            active_from="now",
        )
        print(f"  Created: {new_reg.id}  status={new_reg.status}")
        print(
            "  Note: clothing is exempt from PA sales tax. Stripe applies\n"
            "  this automatically when product tax codes are set to a clothing\n"
            "  category. Verify with a PA shipping address at Stripe Checkout."
        )
    except stripe.error.StripeError as e:
        bail(f"Could not create PA registration: {e}")


# =============================================================================
# 6. Existing webhook endpoints (informational)
# =============================================================================

banner("6. Existing webhook endpoints (informational)")

try:
    endpoints = stripe.WebhookEndpoint.list(limit=100)
except stripe.error.StripeError as e:
    print(f"  (could not list webhook endpoints: {e})")
    endpoints = None

if endpoints is None or not endpoints.data:
    print("  (none)")
    print()
    print("  Dev uses `stripe listen --forward-to localhost:8000/webhooks/stripe/`")
    print("  which forwards test-mode events through the Stripe CLI without")
    print("  registering a permanent endpoint. The production endpoint")
    print("  (https://chesco.io/webhooks/stripe/) gets registered at Sprint 5")
    print("  launch \u2014 either via dashboard or via a follow-up script.")
else:
    for e in endpoints.data:
        evts = len(e.enabled_events) if e.enabled_events != ["*"] else "all"
        print(f"  {e.id}  {e.url}  events={evts}  status={e.status}")


# =============================================================================
# Done
# =============================================================================

banner("Done")
print(
    "Next steps:\n"
    "  - Run `stripe listen --forward-to localhost:8000/webhooks/stripe/` in a\n"
    "    second terminal, copy the whsec_ secret into STRIPE_WEBHOOK_SECRET in\n"
    "    .env, then restart Django runserver.\n"
    "  - Place a test order using card 4242 4242 4242 4242 with a PA shipping\n"
    "    address. Stripe Checkout's tax breakdown should show $0.00 sales tax\n"
    "    for clothing line items.\n"
)
