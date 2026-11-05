# SIZE-UNDER-CAPS — r1
Status: DRAFT; architect + prediction-market-reviewer approval pending. Planning only; no files written or tests run.

## Finding → resolution

Numbering follows the two reviews: [architect A-1–A-6; prediction-market P-1–P-6](/tmp/claude-1000/-home-jon-breezy/83eea2b1-e18b-40bb-8838-7106bb5f661f/scratchpad/roi_size_reviews_r0.md:1); each review’s LOW paragraph is item 6.

| Finding | Severity | Resolution with evidence |
|---|---|---|
| A-1: presumed architecture ruling; flat bankroll clip | HIGH | S0 has two options, architect + prediction-market co-sign, and a prerequisite architecture delta. Retain the boundary bound under Option A; no flat-fraction substitute. `docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:1005-1063`; `docs/core/LESSONS.md:64-68`. |
| A-2: family write path and qty/latch changes | HIGH | Remove all family, manifest and trade edits. Deliver pure sizing, serializer and offline report flag only; later consumption takes `size()` directly under a new PREREG. FQ fixes both quantities to `Literal[1]` and documents same-call qty-1 latching: `src/breezy/strategy/forecast_quantile_ladder/decision.py:73,168`; `src/breezy/strategy/forecast_quantile_ladder/persistent_latch.py:64-67`. |
| A-3: ledger overrides operator D2 | MEDIUM | Use `B_eff = min(operator_D2_bankroll, ledger_B)`; §6.4’s portfolio fraction is a separate exposure ceiling. `docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:1106-1138`. |
| A-4: missing CONTRACT; invalid probability | MEDIUM | Add parsed-instrument equality CONTRACT; `p_lb >= 1` raises. `docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:1101-1104`; `src/breezy/adapters/polymarket_us/parsing.py:1443-1448`. |
| A-5: depth/price narrowing | MEDIUM | Aggregate Depth10 quantity at or better than the limit, excluding own rests; explicitly rule the limit-price valuation approximation in S0. Final recheck remains a tripwire under the conservative fee guard below. `docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:1018-1024,1074-1083`. |
| A-6: ownership/citations/invariants | LOW | S0 belongs to architect + prediction-market-reviewer. Preserve operator controls and qty-1 families; no codegraph caveat. Controls and own-rest deductions verified: `src/breezy/adapters/polymarket_us/operator_controls.py:143-158,535-570`; `src/breezy/strategy/no_ladder_maker/strategy.py:513-531`. |
| P-1: bypassed decision accessor | HIGH | Every Stage 2 ledger input comes exclusively through `read_roi_for_decision`; `None` produces zero. Require A3 import enforcement and executable `lint-imports` RED proof. `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-01_r2.md:8`. |
| P-2: invented bankroll reconstruction | HIGH | Delete opening-allocation/flows arithmetic. Use accessor `available_capital` as conservative spendable `ledger_B`; missing required schema-6 fields or capital means zero. Label balance evidence “lagged ≤ 1 day.” Same AUD-04 delta `:10-11`. |
| P-3: unrounded/per-unit fee substituted for order fee | HIGH | Define authoritative rounded `fee_total`; check exact final-q break-even, equality refusing. A separately derived upper bound only provides conservative admission/affordability. `src/breezy/adapters/polymarket_us/fees.py:314-353,419-432,627-635`. |
| P-4: depth excludes better levels/own rests | MEDIUM | Multi-level at-or-better aggregation, bought-leg orientation and own-rest exclusion become fixtures. Existing exclusion semantics: `src/breezy/strategy/no_ladder_maker/strategy.py:513-531`; Depth10 requirement: `docs/core/LESSONS.md:188-192`. |
| P-5: missing refusal fixtures | MEDIUM | Add missing/stale view, each accessor gate, `n_labels_gated > 0`, maker-zero and rebate-credit refusal tests. Accessor gates: AUD-04 delta `:8`; maker estimate can otherwise return a rebate: `src/breezy/adapters/polymarket_us/fees.py:428-449`. |
| P-6: persistence exception and fee citation | LOW | Serializer has no filesystem writer; embed proposals in existing ROI output and reuse its atomic writer. No new persistence unit or 10-21 exception. `scripts/analysis/portfolio_roi_report.py:2879-2890,4671-4682`; authoritative fee and unrounded estimate distinguished above. |

## 1 Objective + ROI mechanism

GOAL STATE: deterministic, bounded offline quantity proposals, with auditable refusals and no execution consumer.
WALK: frozen inputs → accessor-gated financial view → pure `size` → serializer → existing private ROI report.
ROI mechanism: eligible additional fills can convert a proven positive net edge into additional dollars within authorised capital and caps; this item itself earns $0.
Later family evidence must compare net portfolio ROI and capital lock against its preregistered baseline; larger dollar P&L alone is insufficient.

## 2 Preconditions/dependencies

S0 and ROI-LEDGER A3/A5 must land before implementation; accessor/schema-6 capability is planned, while the inspected report remains v5 (`scripts/analysis/portfolio_roi_report.py:2129-2139`; AUD-04 delta `:8-14`).
Consumption is a later per-family delta gated on GAP-4 PREREG and applicable GAP-1→2→3/5 evidence; Kalshi additionally needs GAP-6 GO and its adapter.
No eligible family or economic PASS is asserted here.

## 3 Scope

Production targets, all proposed: NEW `src/breezy/domain/sizing.py`; NEW `src/breezy/persistence/sizing_proposal.py`; extend `scripts/analysis/portfolio_roi_report.py` with only `--sizing-inputs PATH`.
Supporting changes: focused tests and the A3 import-linter contract in `pyproject.toml`; prerequisite S0 architecture documentation.
No edits under `src/breezy/strategy/**`, to `trade.py`, `family_manifest.py`, operator controls, execution, ledgers, services or timers.
The domain function receives immutable values and a deterministic fee callable; it performs no I/O, clock/environment reads or imports of report/accounting providers.
Native verdict: NATIVE EXISTS, DECLINED because `FixedRiskSizer` sizes stop-distance risk, unlike this settlement-exposure policy (`.venv/lib/python3.13/site-packages/nautilus_trader/risk/sizing.pyx:181-200`).
Keep existing layer direction; domain must not import adapters or offline analysis (`pyproject.toml:74-100,152-160`).

## 4 Steps — owners, inputs, outputs, estimates

S0 — architect + prediction-market-reviewer, estimated 0.5 day: co-sign exactly one §6.2.1 option; land the dated architecture delta before implementation.
Option A: admit §6.2.1’s off-decision-path boundary calibration; freeze market/price/fee/epsilon-specific cap-policy tables and their hashes, with no runtime Kelly arithmetic.
Option B: reject that interpretation; BLOCK implementation pending an architecture rebuild. The documented fractional-Kelly fallback requires a separate explicit ruling against the existing ban; this item cannot activate it (`docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:974-1001,1055-1063`).
S0 also rules the limit-price approximation, conservative fee guard, bankroll basis and every property below; no blanket “conservative sizing” claim.
Follow L-12: search pins before shared-config edits; any necessary exact-set widening receives its own reviewed re-pin, never a relaxed comparison (`docs/core/LESSONS.md:64-68`).
S1 — implementer, estimated 1 day after S0: RED-first pure sizing and property evidence.
S2 — implementer, estimated 0.5 day after ROI-LEDGER: strict serializer and offline flag integration; output one existing ROI report containing the proposal.
S3 — both reviewers: assess attributable gate evidence and acceptance; close as proposal machinery only.

Stage 1 contract:
`size(p_lb, price, depth_at_price, B_eff, caps, policy, fee_total) -> Decimal proposed_qty`; quantities are contracts, money is USD, all arithmetic Decimal.
Validate finite inputs, `0 <= p_lb < 1`, `0 < price < 1`, positive increment/minimum and required policy/headrooms; `p_lb >= 1` raises.
`price` is the bought-leg limit valuation, not a claimed depth-weighted execution price; S0 explicitly updates §6.2/§6.4.1 for this approximation (`docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:1018,1132-1138`).
`depth_at_price` is visible executable quantity across Depth10 levels at or better than that limit, excluding own rests; never QuoteTicks, extrapolated levels or assumed maker fills.
`side` in `fee_total(q, price, side)` means MAKER/TAKER; YES/NO bought-leg identity is separate.
Bind the market’s verified θ in the callable: taker delegates to `polymarket_us_fee`, rounding the total order fee to cents with ROUND_HALF_EVEN; maker returns zero; no rebate credit; missing θ or unknown side refuses (`src/breezy/adapters/polymarket_us/fees.py:314-353,459-501,627-635`).
Never substitute `expected_fee_for`; it is unrounded and uses a documented fallback coefficient (`src/breezy/adapters/polymarket_us/fees.py:419-456`).
Derived sufficient guard: for admitted `q >= min_quantity`, taker `u = θ*price*(1-price) + 0.005/min_quantity` bounds `fee_total(q)/q`; maker `u=0`. This follows from cent rounding, not a second fee schedule.
Require `p_lb > price + u + epsilon`, with frozen `epsilon >= 0`; this extra refusal preserves depth/cap monotonicity despite rounding. S0 must explicitly approve its opportunity cost.
Option A calibrates the offline boundary fraction against this same guard; absent/invalid policy entry, or boundary probability ≥1, returns zero.
Let `a` be §6.4’s operator-authorised portfolio fraction, never the boundary-cap replacement; `H_portfolio=max(0,a*B_eff-existing_cost_basis_and_reservations)`.
Set `H_bank=min(H_portfolio,available_capital_after_reservations)`; supplied headrooms must count held/working commitments once and refuse unknown exposure.
For money headroom `H`, use `M(H,c)=floor_increment(floor_cent(max(0,H))/c)`.
Candidate = minimum of boundary-cap contracts, depth, cluster/city-day/day headrooms, position/daily premium bounds at `price`, and bankroll bound at `price+u`; floor once to increment, below minimum → zero.
At final positive q require `p_lb > price + fee_total(q,price,side)/q + epsilon`; specifically `p_lb <= price + fee_total(q)/q` returns zero, including equality.
Recheck exact fee-inclusive affordability, cent-ceiled premium and every cap; failure returns zero, never searches for a passing smaller quantity. Premium rounding matches `src/breezy/adapters/polymarket_us/operator_controls.py:281-295`.
Under unchanged single-price inputs and the sufficient guard, final checks are tripwires; they do not establish multi-level fill economics or partial-fill fee equivalence (`src/breezy/adapters/polymarket_us/fees.py:216-235`).

Stage 2 contract:
All ledger-derived inputs—realised P&L, open cost basis and available capital—come ONLY from `read_roi_for_decision(path,now)`; operator policy and market inputs remain separately identified.
Accessor `None`, missing required schema-6 family fields, or `available_capital is None` → `H_bank=0`, zero proposal; never fall back to report scalars.
Define `ledger_B=view.available_capital` as conservative spendable bankroll, then `B_eff=min(operator_D2_bankroll,ledger_B)`; no reconstructed equity, opening allocations, flows or additional P&L credit.
Losses can shrink proposals; gains can restore capacity only within authorised D2 and unchanged caps. Never replenish gross daily spending from profits.
Require A3 gates: schema 5/6, OK ROI and D8 status, aware `generated_at` age ≤24h, zero unverified fees and zero gated labels; v5’s missing schema-6 fields still block sizing (AUD-04 delta `:8-10`).
Require the balance observation’s own age ≤24h; label its evidence “lagged ≤ 1 day”; exposure is cost basis plus fee, not marked value (AUD-04 delta `:10-11`).
A3 owner must supply an enforceable accessor/provider import boundary: ordinary module contracts cannot pretend function names are modules. Block direct raw-provider imports in sizing/serializer and, later, each family consumer.
The report’s existing reporting branch may retain raw reporting APIs; its sizing branch must exclusively call the accessor, with a separate call-path test proving no raw fallback.
`--sizing-inputs` carries frozen market/operator inputs and the ROI-source path/hash, never replacement financial scalars; embed proposal fields in the existing private JSON/Markdown publication.
Serializer only encodes/validates data: policy/code/PREREG hashes, input timestamps/source hashes, basis, q, binding constraints and refusal reasons. No standalone proposal file, reader-based execution handoff or new persistence unit.
Later family consumption calls `size()` directly; the report is an observability sidecar. That delta owns partial fills, IN_FLIGHT/latch semantics and final in-lock authorisation.

## 5 Acceptance — frozen §6.3 property disposition

| Property | Kept/dropped and reason |
|---|---|
| Finite nonnegative size | KEPT: validate inputs; output zero or finite nonnegative Decimal. |
| Every individual cap | KEPT: minimum construction plus final monetary checks. |
| Visible-depth bound | KEPT: candidate clips to own-rest-excluded Depth10 quantity. |
| Boundary fraction × bankroll bound | KEPT under Option A; include in offline-policy proof and properties. Option B blocks implementation. |
| Inclusive break-even/epsilon refusal | KEPT: exact final-q predicate, plus explicitly approved stricter sufficient guard. |
| Depth below minimum → zero | KEPT: no rounding up. |
| Increment alignment | KEPT: floor to instrument increment. |
| Depth/cap monotonicity | KEPT for fixed other inputs: q-independent sufficient guard avoids rounded-fee refusal discontinuities. |
| Probability monotonicity not required | KEPT as a non-requirement; edge magnitude above the gate does not scale quantity. |
| Probability 1 raises | KEPT and extended to all `p_lb >= 1`. |
| Separate instrument CONTRACT | KEPT: fail if parsed `min_quantity != size_increment`; synthetic mismatched minima also exercise refusal. |

Source for the complete list: `docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:1085-1104`. No property is silently dropped.
PASS requires deterministic proposals, all properties, accessor isolation and existing report compatibility; any breach means revise/KILL the implementation, never relax a barrier.
Engineering PASS establishes machinery only; family economic PASS/KILL remains its frozen rule, with no extra independent trials from quantity or partial fills.

## 6 RED-first tests + gate

Add proposed `tests/unit/test_cap_depth_sizing.py`, `tests/unit/test_sizing_proposal.py`; extend `tests/unit/test_portfolio_roi_report.py`.
Test all properties; exact/equality/epsilon boundaries; `p_lb=1` and >1 raising; exhausted caps; unequal synthetic minima; multi-level bought-leg depth and own-rest exclusion.
Fee fixtures: θ=.06, price=.50, q=1 → .02; q=3 → .04; maker zero; rebate-credit rejection; missing θ; final-check helper equality and affordability tripwires.
Accessor integration: missing/stale view, unknown schema, naive/missing timestamps, D8 failure, unverified fees, `n_labels_gated>0`, v5 missing fields, stale balance and accepted complete v6.
Prove `lint-imports` RED on forbidden raw imports in sizing/serializer and a representative future-consumer fixture; restore GREEN. Later consumer must join the contract before landing.
Test real serializer/report round trips, default invocation compatibility, conflicting flags, atomic-write failure and deterministic source hashes; mutate clamps/gates/import barriers, observe failure, restore GREEN.
Run focused tests through the existing wrapper, then `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/size-under-caps` and `.venv/bin/lint-imports`; inspect EXIT before any requested push (`scripts/ci/run_tests_no_egress.sh:25-35`; `docs/core/LESSONS.md:354-356`).

## 7 Pins/isolation/risks

Nautilus immutable; `allow_short=False`; preserve every safety/settlement/contract/pin/NO-SEND barrier; operator owns caps, concrete q and arming.
Existing harness only; isolated HOME/data fixtures; no live probes, credentials/order IDs in git, or `iem_cli_fetch.fetch`; retain holdout clauses 1–4 and frozen PREREG/ONE-look discipline.
L-75 requires writer-produced evidence and separate commentary sidecars (`docs/core/LESSONS.md:409-413`).
Capital-lock policy remains conservative for seven-day resolution; no assumed daily turnover (`docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:1157-1162`).

## 8 Operator decisions

Operator supplies D2, portfolio allocation authority, existing caps and later family quantity/PREREG authority; this plan proposes no numeric value.
Arming and per-family consumption remain separate later decisions; neither report publication nor engineering PASS authorises execution.

## 9 Unverified / pending

- S0 co-signatures, its architecture delta and offline boundary-policy proof remain pending.
- A3/A5 accessor implementation, enforceable provider separation and complete schema-6 financial provenance were not verified as delivered.
- Family PREREG eligibility, scaled partial-fill economics and live executable-depth freshness remain unverified; all consumption is deferred.
- Tests/gates were not run; Sequential Thinking MCP was unavailable.

Codex session ID: 01a19978-b73a-74b1-b770-2dc8a5d59ded
Resume in Codex: codex resume 01a19978-b73a-74b1-b770-2dc8a5d59ded
