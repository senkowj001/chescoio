# Sprint 1 Implementation Prompt — Foundation & Multi-Brand Scaffolding

## Context

You are implementing Sprint 1 of the East Goshen Apparel Platform, a multi-brand print-on-demand storefront built in Django. The first brand front is `chesco.io` (Chester County, PA local-pride apparel). The full sprint plan is in `eg_apparel_sprint_plan.md` — read it before starting.

The developer is John, who runs East Goshen Technologies. He maintains a portfolio of Django/Heroku projects at `C:\django\prod-django\` on Windows. He uses the filesystem MCP toolchain for direct project editing. He prefers direct recommendations over option menus, staging before production, and honest pushback when plans have technical flaws.

## Sprint 1 goal

Stand up a deployed Django app on Heroku with multi-brand hostname routing, admin-creatable Brand model, and brand-aware base template rendering. No products, no cart, no payments yet. The `chesco.io` domain should resolve to a "Coming Soon" page rendered with brand-specific colors and tagline.

## Pre-work (do this first, in order)

1. Read the full sprint plan at `eg_apparel_sprint_plan.md`, focusing on the "Architectural decisions, locked" section and "Sprint 1" section
2. List the existing projects in `C:\django\prod-django\` to identify the patterns to mirror — specifically HuntScrape (for Tenant middleware → Brand middleware) and Honey & Pine (for Tailwind CDN setup)
3. Read the HuntScrape `settings/` directory structure, `Procfile`, and main middleware module — these are the templates to copy from
4. Confirm with John before starting: which Heroku account, which GitHub repo name, and whether the Printify shop already exists or needs to be created

## Implementation order

Work in this sequence and commit after each step:

1. **Project skeleton** — `django-admin startproject eg_apparel` in `C:\django\prod-django\eg_apparel\`. Create apps `brands`, `catalog`, `orders`, `core`. Mirror HuntScrape's `settings/base.py`, `settings/dev.py`, `settings/prod.py` split.

2. **Brand model and admin** — Implement the `Brand` model from the sprint plan exactly. Register in admin with all fields visible. Run initial migration.

3. **Brand middleware** — Implement `BrandMiddleware` from the sprint plan. Add to `MIDDLEWARE` after `SecurityMiddleware`. Handle the `www.` prefix correctly. Return a branded 404 for unknown hostnames (except `/admin/` paths).

4. **Base template** — Build `templates/base.html` with HTMX + Tailwind via CDN (mirror Honey & Pine). Render brand colors as CSS variables in `:root`. Conditionally include Plausible and Meta Pixel based on Brand fields.

5. **Homepage view** — Single view at `/` that renders a "Coming Soon" template using the brand's name, tagline, and primary color. Simple, clean, no marketing copy yet — that comes in Sprint 5.

6. **Heroku setup** — Create the Heroku app, add Postgres Essential-0 and Scheduler addons, configure env vars, write the `Procfile` with `release: python manage.py migrate`. Deploy from main branch.

7. **Cloudflare DNS** — Point `chesco.io` and `www.chesco.io` at Heroku. SSL mode Full (strict). Apply the SSL redirect fix from HuntScrape (`SECURE_SSL_REDIRECT = not DEBUG`, with proper `SECURE_PROXY_SSL_HEADER`).

8. **Seed the first Brand** — Create the `chesco.io` Brand record via a data migration (preferred) or Django shell. Use the values from the sprint plan's seed example.

9. **Verify acceptance criteria** — Run through the Sprint 1 acceptance criteria checklist from the sprint plan. All items must pass before sprint is complete.

## Critical reminders

- **Stage before production.** Deploy to a staging Heroku app first (`eg-apparel-staging`), verify, then promote to `eg-apparel`.
- **No secrets in code.** `PRINTIFY_ACCESS_TOKEN`, `STRIPE_SECRET_KEY`, etc. are env vars only. None should appear in this sprint's code yet, but set the pattern.
- **Reuse, do not rewrite.** If a pattern exists in HuntScrape or Apeirum, copy it. The goal is consistency across the East Goshen portfolio.
- **Migrations are reviewed before deploy.** Show John each migration before running it in production.
- **Multi-brand is non-negotiable from day one.** Do not take shortcuts that hardcode chesco-specific values anywhere outside the seeded Brand record.

## When to ask, when to act

**Just do** — anything explicitly in the sprint plan, anything that mirrors an existing East Goshen project pattern, anything covered by the acceptance criteria.

**Ask first** — any deviation from the architectural decisions in the sprint plan, any new dependency not listed in the stack lock, any field added to the Brand model beyond what's specified, anything that would require changes to other East Goshen projects.

**Push back if** — you see a flaw in the plan as written, you spot something that conflicts with HuntScrape's patterns in a way the plan doesn't address, or the developer asks for something that would create technical debt. John explicitly values honest pushback.

## Definition of done

Sprint 1 is complete when all eleven acceptance criteria from the sprint plan pass on the production Heroku app at `https://chesco.io`, the code is on `main` in GitHub, and the Brand admin shows the seeded chesco record. Update the sprint plan document with any decisions made or deviations taken so the source of truth stays current.
