# S4 r1 review — Codex (venue API / order lifecycle) — 2026-10-12
Verdict: UNSOUND — the STOP threshold and the no-id AMBIGUOUS path contradict each other, and a no-id resting POST can orphan a live order across a restart.

## Findings (ranked)
1. [BLOCKER] Plan §3 STOP threshold for cancels is wrong. It stops only if per-order cancel AND slug-scoped cancel-all are both unavailable, but WP5's no-id AMBIGUOUS path REQUIRES slug-scoped cancel-all before negative retirement; per-order cancel cannot cancel an order with no venue id. Evidence: plan :40-43, :208-210; venue docs expose per-order cancel and cancel-all separately, cancel-all optionally filtered by market: `api-reference_orders_overview_2026-08-25.md:47-60`; SDK `CancelOrderParams.marketSlug` / `CancelAllOrdersParams.slugs`: `types/orders.py:147-156`. Required: slug-scoped cancel-all becomes a hard precondition (STOP if absent).
2. [BLOCKER] Restart/disconnect safety leaves a possible orphan after a no-id AMBIGUOUS resting POST. The boot sweep cancels only map-bound orders; a no-id create has no venue id / client id binding; if the process dies before slug cancel-all confirmation, boot refuses/alerts but does not necessarily remove the live order. Evidence: plan :177, :208-210; no client-order-id in create body, no-id ambiguity only tuple-resolvable: `.claude/skills/polymarket-us-integration/SKILL.md:333`, `submit_chain.py:100-103`. Required: boot sweep = slug-scoped cancel-all on every slug the family touched (durable slug ledger), then confirm by read.
3. [MAJOR] Fill discovery by 30 s `query_order` polling is safer than Nautilus open-order consistency checks, but underweights the venue's private order stream (accept/fill/reject/cancel events): `api-reference_orders_overview_2026-08-25.md:63-68`; market WS TRADE is forward prints only, not account fills (skill :325). Polling acceptable only if by-id reads are authoritative and poll/read failures latch loudly. Plan :59-65, :76, :199-207.
4. [MAJOR] Resting GTC/GTD BUY NO without `post_only` is schema-plausible but unproven for weather markets. Docs allow GTC/GTD and NO buy; `participateDontInitiate` is optional and the only maker-only guarantee. Unsafe until WP0/WP6 proves it. Evidence: skill :144-148; create docs :82-89, :160-174; NO price inversion `orders_overview:141-158`; plan :24, :47, :106, :231.
5. [MINOR] Maker fee sign: skill pins maker θ as −0.0125 rebate while spec examples use positive fee math; plan mostly handles this by reading venue commission/fill fields. Evidence: skill :184-188; spec :103-112; plan :111, :201-204.

## Cited-vs-actual mismatches
- Slug cancel-all is not optional for no-id safety.
- Private WS is documented even if not locally snapshotted.
- Maker fee sign is negative in the skill.
- No-post-only resting acceptance on `tc-temp-*` remains unverified.

## What the plan gets right
- Current code accurately identified as IOC-only with cancel stubs: `submit_chain.py:331-353`, `client.py:7587-7613`.
- NO wire-price inversion consistent with the known §6.1 defect: plan :15, `leg_prices.py:56-74`.
- 10 market-subscriptions-per-connection cap not worsened by avoiding private WS; eight active order slugs fit under one market connection: skill :293, :309, :311.
