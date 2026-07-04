# East Goshen Apparel — Sprint Prompts Index

This folder contains six sprint implementation prompts plus the master sprint plan. Each prompt is designed to be self-contained: hand the prompt file plus `eg_apparel_sprint_plan.md` to a focused Claude session and it should have everything needed to execute that sprint.

## Files

- `eg_apparel_sprint_plan.md` — Master sprint plan. The source of truth for architecture, models, and acceptance criteria. **Always attach this alongside the sprint prompt.**
- `prompt_sprint_1.md` — Foundation & multi-brand scaffolding
- `prompt_sprint_2.md` — Printify integration (product sync, list/detail pages)
- `prompt_sprint_3.md` — Cart & Stripe Checkout
- `prompt_sprint_4.md` — Printify order submission & status sync
- `prompt_sprint_5.md` — Polish, legal, SEO & launch
- `prompt_sprint_6.md` — Launch recovery & production cutover (fixes the failed release, removes "Coming Soon," surfaces the contact page, Stripe live cutover, email deliverability, publishes legal pages)

## How to use these prompts

1. Start a new Claude session
2. Attach `eg_apparel_sprint_plan.md` and the sprint prompt file for the sprint you're working
3. Confirm the pre-work items at the top of the prompt before any coding starts
4. Work through the implementation steps in order
5. Do not advance to the next sprint until all acceptance criteria for the current sprint pass on production

## Order of operations

The sprints are dependency-ordered. Do not parallelize or skip:

- Sprint 1 must be deployed and verified before Sprint 2 starts
- Sprint 2 must have products syncing before Sprint 3 (cart needs real products)
- Sprint 3 must have orders being created before Sprint 4 (fulfillment needs orders)
- Sprint 4 must be sending real emails before Sprint 5 (launch needs email working)
- Sprint 5 is the launch gate — do not announce publicly until every checklist item is verified

## Working norms across all sprints

- **Stage before production.** Every sprint deploys to staging first, then promotes.
- **Reuse from existing East Goshen projects.** HuntScrape, Apeirum, Honey & Pine. Do not reinvent.
- **Update the sprint plan when reality diverges.** The plan is the source of truth — keep it current.
- **Push back honestly.** Each prompt explicitly invites this. John values it.
- **Acceptance criteria are binary.** "Mostly works" is not done.

## When something goes wrong mid-sprint

If a sprint runs into an issue that requires a decision outside the plan's scope:

1. Stop coding
2. Document the issue in chat
3. Propose 1-2 options with tradeoffs
4. Wait for John's decision
5. Update the sprint plan with the chosen path before resuming

This is more efficient than charging ahead and discovering rework later.

## Post-launch (after Sprint 5)

The 2.0 list is in the sprint plan's "Post-launch / 2.0 list" section. Priority order to confirm with John post-launch:

1. B2B custom order intake form (the actual revenue lane)
2. Real product photography (replaces Printify mockups)
3. Second brand front launched on same backend (validates the multi-brand architecture)
4. Etsy storefront integration (additional sales channel)

Everything else on the 2.0 list waits until at least one of these is shipped.
