# AUD-13 round-6 delta review — trading-bot-architect

Plan: AUD-13-native-venue-reconciliation-from-durable-records.md
SHA256: 0c3a1347c68db9277259c63cce78565f10c6dbf478963a2029ea866681f17ac0
Round: 6 (ruling-application delta, FINAL for this cluster)
Reviewer: trading-bot-architect (blind — no other agent's output consulted)

## Scope

Verify the plan applies `RULING_venue_reconciliation_R1_R2_2026-09-21.md` (Revision 3,
peer-ENDORSED, no required change) faithfully, through Nautilus's native reconciliation
semantics, and test the new §12 "no blocker remains" claim. Read the ruling and its full review
trail (Revisions 1-3) before reading the plan's diff, and verified every load-bearing citation
against source independently rather than trusting either document's account.

## Claims verified against source this session

| Claim | Verdict |
|---|---|
| `FillReport.commission: Money` is required, non-nullable (`execution/reports.py:641,676`, "If no commission then use a zero `Money` amount") | CONFIRMED |
| `DurableFillRecord` at `exec/client.py:641`; `order_side: str` at `:670`; `cumulative_fee`/`fee_reconciled`/`venue_fee_raw`/`trade_id`/`order_qty` at `:673,674,676,681,685` | CONFIRMED, all present |
| `_to_json`/`_from_json` use `payload.get(...)` for `venueFeeRaw`/`tradeId`/`orderQty` (`:757-759`) — the established optional-on-read pattern the plan cites for the two new fields | CONFIRMED — this is a real, working migration/compat mechanism already proven in this store, not an invented one |
| `polymarket_us_fee` reads `theta` via `_fee_coefficient(instrument)` at call time, no fill-time parameter (`fees.py:277,304,422`) | CONFIRMED — this is the defect the ruling's HIGH finding turns on |
| `consume_if_absent` at `trial_day_latch.py:780`; `authorize_order_cost` has zero call sites under `src/breezy/strategy/` | CONFIRMED |
| SELL routes to `_on_exit_order_filled`, never the entry path (`continuous_strategy.py:2271-2277`, comment: "Breezy never submits any OTHER SELL... a SELL fill is unambiguously an EXIT fill") | CONFIRMED — finding 8's failure mechanism is real |
| `external_order_claims` / `nautilus_trader/trading/trader.py:435` (13c's native mechanism) unchanged by this revision | CONFIRMED, correctly untouched — R2-B's mechanism was never in question, only its conditions |
| Ruling Revision 3's AMBIGUOUS-window boundary (`< 2026-09-17T00:00:00Z` → 0.06; `>= 2026-09-17T17:00:00Z` → 0.0695; the gap between REFUSES) matches the plan's §6/§7/§8 text verbatim | CONFIRMED |
| §12's "no blocker remains" claim | TESTED, HOLDS — the ruling itself states the one still-open item (whether the venue populates `commissionNotionalTotalCollected`) does not block B1 shipping because O4 degrades gracefully without it (unlike the rejected O3); the plan correctly carries this as a non-blocking open question rather than a hidden dependency. The three R-2 conditions are build-sequence items owned by this same plan, not an external ruling or unavailable evidence — correctly not classified as blockers. |
| §10 rollback | Not edited, and does not need to be: "B0's record fields are optional-on-read... a revert leaves every store row decodable" already generalizes correctly to the two new ruling-mandated fields, which the plan states follow the identical pattern. |

## Defect found

**MINOR-to-moderate, architecture — the dated fee-schedule table's module ownership is
unspecified, and this is the exact "fork of `fees.py`" risk the coordinator named.**
`src/breezy/adapters/polymarket_us/fees.py` already has an established, working pattern for
exactly this kind of artefact: `DOCUMENTED_TAKER_FEE_COEFFICIENT` (`:86`) and
`MAKER_FEE_COEFFICIENT` (`:77`) are both module-level constants pinned from a dated evidence
document, each with a docstring stating its provenance and scope — this module's own stated
purpose is to be the single place Polymarket.us fee numbers are derived and pinned (its own
docstring: "What remains genuinely ours is... a thin subclass of the native `FeeModel`
extension point — no parallel abstraction, no reimplementation"). The ruling's new dated schedule
(`{< 2026-09-17T00:00:00Z: 0.06, >= 2026-09-17T17:00:00Z: 0.0695}`, sourced from
`FEE_SCHEDULE_PIN_2026-09-18.md`) is the same kind of artefact — a dated, evidence-pinned fee
coefficient — but neither the ruling nor this plan's §6/§7 states which module holds it. The
plan's only `fees.py` citations are to the two existing, unmodified functions
(`polymarket_us_fee:277`, `_fee_coefficient:422`); nothing says the new schedule constant or the
as-of-`ts_event` resolver function is added to `fees.py` beside them, versus being defined
ad-hoc inside `exec/client.py` where `DurableFillRecord` and the generators live. An implementer
following the plan as written has no stated reason to put the schedule in `fees.py` rather than
next to the code that consumes it — and the latter choice would create exactly the fork the
coordinator's brief flags: two places a fee coefficient can be looked up, one of them outside the
module whose entire charter is to be that single source of truth, with no cross-reference between
them and no test pinning that only one exists.

**Required change:** one sentence in §6's ruled-design block naming the module: the dated
schedule constant and its as-of-`ts_event` resolver (e.g. a new `_fee_coefficient_as_of(ts_event:
datetime) -> Decimal | None` beside the existing `_fee_coefficient(instrument)` at `fees.py:422`)
live in `fees.py`, exported alongside `DOCUMENTED_TAKER_FEE_COEFFICIENT`, and `exec/client.py`'s
generator bodies call it rather than embedding a second lookup table. This is a one-line
architectural pin, not a design change — it makes explicit what the module's own existing
pattern already implies, and closes the fork risk before an implementer has to guess.

No other defect found. Every citation in the ruling-application diff was re-verified against
installed source or the repo's own artefacts this session, independent of the ruling document's
own account, and all held.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | The ruling is applied to every section it touches (§4 dependencies, §5 scope, §6 design, §7 ordered steps, §8 acceptance, §12 blockers), with nothing from the ruling left unincorporated — the non-reorderable build order, both R-1 branches, the AMBIGUOUS-window refusal, R-2's three conditions, and the safety constraints are all present. |
| Technical correctness and evidence grounding | 20 | 19 | Every citation checked against source this session and correct, including the ones the ruling's own review trail fixed across three revisions (fill-time θ, the closed-interval boundary). Deducted 1 for the module-placement gap above — a real, if narrow, evidence-grounding omission: the plan asserts a computation "exactly as `polymarket_us_fee` does" without stating where the new computation it requires actually lives. |
| Implementation specificity and feasibility | 15 | 13 | The B0 fields, the build order, the refusal semantics, and the three named RED tests are all literal. Deducted 2: the schedule's module ownership (the defect above) is the one genuinely unspecified architectural decision in an otherwise fully-specified revision, and it is exactly the kind of gap that produces a silent fork if left to an implementer. |
| Acceptance criteria and validation quality | 20 | 20 | Sixteen items now, with three new ones (13-16) pinning the order-side fix, the fill-time-coefficient test, the AMBIGUOUS-window refusal, and the no-new-ledger-call-site/still-RESIDUAL safety facts as diffs/greps rather than prose claims. |
| Autonomous operation, failure handling and recovery | 15 | 15 | The AMBIGUOUS window refuses rather than guesses (fail-closed on money, the correct direction); the order-side fix closes a real phantom-entry hazard under both R2-A and R2-B; the safety constraints (no new ledger call site, `venue_order_id`-keyed idempotency, RESIDUAL-not-`n`-growing) are restated as binding rather than assumed. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No operator-reserved value touched; §12's "no blocker" claim is tested and holds; the residual third-drift-point risk is named as a known limit of the ruling, not hidden. |
| **Total** | **100** | **97** | |

## Required changes

One: name the module (recommended `fees.py`, beside `_fee_coefficient`/`DOCUMENTED_TAKER_FEE_COEFFICIENT`) that owns the dated fee-schedule constant and its as-of-`ts_event` resolver, so the fallback computation has one stated source of truth rather than a silently-permitted fork between `fees.py` and `exec/client.py`.

## Blockers

None. R-1 and R-2 are RULED and peer-ENDORSED with no required change on the ruling itself
(Revision 3). §12's "no blocker remains" claim was independently tested against the ruling's own
text and holds: the three R-2 conditions are internal build-sequence items owned by this plan,
and the one still-open item (venue `commissionNotionalTotalCollected` population) does not gate
B1 under the ruled O4 design.
