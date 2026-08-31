# Order-egress plan — round 3 adversarial review, merged

**Reviewed:** `ORDER_EGRESS_PLAN.md` revision 3 (2246 lines, commit `48f0bd0`).
**Lenses:** structure/goal-state, Nautilus contract fidelity, prediction-market
domain math, security/containment. Four dispatched, four returned.

## Verdict: BLOCK (4/4 lenses independently)

## The decisive result is not any single finding

| Round | Findings |
|---|---|
| 1 | 16 blocking |
| 2 | 5 criticals; 15 of 16 round-1 findings genuinely closed — **converging** |
| 3 | ~7 criticals, ~10 highs, **most newly created by revision 3's own fixes** |

**The plan is diverging.** Round 2 already showed 3 of its 5 criticals were
introduced by round-1's repairs; round 3 shows 5 of 6 structural findings and
both settlement criticals were introduced by round-2's repairs. Two consecutive
rounds is a pattern, not noise.

**Mechanism.** One document designs the settlement identity, the four-type
authority algebra, and the container/ordering simultaneously, with dense
cross-references. Each local fix satisfies its named finding without re-running
the global consistency checks, and perturbs two other areas. Four of round 3's
findings are the SAME failure: an edit that did not propagate to every other
site asserting the same fact (ND-2, S-1, ND-5, and the two stale settlement
rows). That is mechanically preventable — see LESSONS L-4.

## Decision taken

**Cut the plan at the NO-SEND / SEND seam.** Revising the monolith a fourth
time repeats a process that has now failed twice.

- **IN, as `EXEC_CLIENT_NOSEND_PLAN.md`:** old E-0..E-4 — egress firewall for
  `exec/`, cage/permit strengthening, the trading process, endpoints + report
  mappers on the existing GET stack, and a fully-reconciling execution client
  that refuses every order. All NO-SEND; cannot lose money; findings against it
  are specification defects, not design divergence.
- **DEFERRED to successor plans:** the denial layer (E-5), settlement-as-exit
  (E-6), order-source enablement (E-7), and every SEND increment (E-8..E-14)
  including the multi-type authority algebra.

The seam is principled, not arbitrary: settlement is not needed until a
position can exist, and multi-type authority is not needed until a write
endpoint exists.

## Criticals, all verified against source by the coordinator

| # | Finding | Evidence |
|---|---|---|
| **C-a** | **`TradeId` is capped at 36 characters; the R2-BL-3 settlement identity is unconstructable.** `TradeId("SETTLE-{slug}-{setTime}-{px}")` → `ValueError: 'value' out of range [1, 36], was 67`. `"SETTLE-" + slug` alone is 39 for a real weather slug. `VenueOrderId` has no cap, so the defect is one-sided and easy to miss. | ran on 1.231.0; slug from `raw/book_open_510636.json` |
| **C-b** | **N-14 is FALSE — a `TradingNode` is built and run today.** `grep "TradingNode("` returns zero only because the class is passed, not called: `node_factory: NodeFactory = TradingNode` (`quote_tape_cli.py:195`, `cli.py:147`) then `node_factory(config); node.build(); node.run()` (`:151-156`). True gap is narrower: no trading-ROLE config, no `breezy-trade` entry point. **Coordinator's error**, tagged `[V]` on a grep whose inference was never tested. | verified directly |
| **C-c** | **The primary settlement source names the wrong endpoint AND the wrong path.** Plan says `GET /v1/markets/{slug}` → `stats.settlementPx`. Both by-slug captures have no `stats` at all; the field is `marketData.stats.settlementPx` in the `/book` response. `bbo_*` carries `marketData.settlementPx` with NO method and NO setTime — same name, none of the gate fields, must be excluded. Implemented literally the primary returns nothing, forever. | `raw/market_*_by_slug.json`, `raw/book_*.json`, `raw/bbo_open_510636.json` |
| **C-d** | **A venue settlement correction becomes either a silent drop or a phantom short.** px-changes/setTime-fixed → same `VenueOrderId`, already FILLED → `_reconcile_fill_report` rejects at `live/execution_engine.py:3333-3341` (`allow_overfills=False`) and the correction is discarded with a warning. setTime-changes → both ids differ → full-size fill on a flat position = the round-2 phantom short, re-entering through the door revision 3 opened. | verified |
| **C-e** | **`POST /v1/orders` is reachable under TWO authority types**, and `ReduceOnlyAuthorization` decrements order count but **not budget** — the operator's dollar ceiling has zero coverage on a path that posts live orders. Contradicts the plan's own disjointness rule at `:795-797`. | plan `:774-778`, `:617-622` |
| **C-f** | **Rule 3 ("union equals the transport allowlist") is vacuous where it is asserted and self-contradictory where it matters.** Asserted at E-1 where `:963` says no allowlist exists yet; never re-asserted per increment; satisfying it literally at E-8 requires `POST /v1/orders` in the allowlist at an increment labelled "cannot open exposure". Nothing pins the NUMBER of authority types at four. | plan `:790-793`, `:1691-1692`, `:862-864` |
| **C-g** | **The settlement fill's side, quantity, `venue_position_id` and emission precondition are still unspecified.** R2-BL-5 was closed only for strategy attribution. A settled market Breezy never traded emits a closing report and OPENS a position at 0.00/1.00. | plan `:1369-1453` |

## Highs

- **ND-1** The container check's own row 4 reads `E-6, needing E-2 + E-7` — a dependency on a LATER increment. The table revision 3 added to prevent this class of error contains the row that indicts it, and the sequencing did not act on it.
- **ND-2** §4.2 deletes `cost_cap = payout_cap × price` and gives E-5 an AST scan banning it; E-5's body at `:1296` still computes it. An implementer following E-5 trips E-5's own scanner.
- **ND-3** Composed-node REDs are unrunnable: `conftest.py` `_block_network_sockets` is autouse and patches `socket.socket.connect` for every test without a network marker, while E-1 bans those markers on exec-importing tests and E-2 refuses to start without Redis. The test-infrastructure decision is never named.
- **ND-4** Alerting has no container in the trading process. `resolve_alert_sink` is wired only into the ingest runtime (`composition.py:45,279,352,369`); every "loud" failure would be log-only in the process that trades.
- **"Redis unreachable → refuses to start" is uncited.** `system/kernel.py:310-329` raises only for an unrecognized `cache.database.type`; it never probes connectivity. A claimed native behaviour the native code does not produce — LESSONS L-2.
- **The inferred-fill branch bypasses `external_order_claims` entirely.** `live/reconciliation.py:511` hardcodes `PositionId(f"{instrument.id}-EXTERNAL")`; the claim only sets the order's `strategy_id`. Same path calls `calculate_commission(..., NO_LIQUIDITY_SIDE)`, which Breezy's fee model raises on (`fees.py:165-170`), swallowed into "reconciliation failed".
- **The three-part settlement gate is validated on 2 positives and 0 relevant negatives** — there is no capture of a TIER_1 market *before* settlement. A free fourth conjunct exists in the same captures: `settlementSetTime` at/after expiration.
- **The three new authority types ship with none of the locks the existing one has** — no `__post_init__` tag verification, no nonce single-use, no constructor-allowlist entry. R2-BL-4's shape repeated.
- **The issuer `== 1` barrier collides with E-9/E-10**, whose operator scripts must dispatch under a permit; every route either breaks the pin or drags an exec factory into a probe script.
- **§6.2's barrier pins cardinality, not identity** — the registered client/strategy can be swapped without failing a barrier.
- **E-2's composition shape is self-contradictory** — claims to mirror the quote tape (inline in `quote_tape_cli.py`, no composition module) AND `composition.py:272-310` (the ingest `@contextmanager` that never touches a node). Later REDs require a function that builds and starts a node; the ingest shape does not.

## Mediums

- **N-10 miscounts:** 7 transitions into FILLED, not 8. The load-bearing half is correct and re-verified: **zero** transitions *from* FILLED.
- **The AST purity scan is a name blacklist defeated by one level of indirection.**
- **E-7 RED (ii-b) requires the bespoke test node E-4 forbids**, and is the wrong control besides.
- **E-6 has no unit-ledger entry** despite being the increment that hands PnL to native machinery.
- **Stale reverted text survives at `:473` and `:2028`.**

## What survived review and should be carried forward

The A-1 egress-firewall closure for `exec/` is genuine, not documented-around.
The issuer `== 0` → `== 1` flip is a real control with a non-vacuity proof.
N-6 (`_query_account` called at `live/execution_client.py:332`, defined nowhere
on the base), N-17 (the claim→`PositionId` chain), N-18 (`exc_types`
set-equality, stable because E-3 defines the raised types itself), and N-20 (the
node-config count pin quantifies over every site) are all TRUE and verified.
§6.2's value table is stronger than the emptiness rule it replaces on four of
five dimensions. BL-10, A-2, BL-12 and the two-directional fail-closed are
correctly specified with paired REDs.
