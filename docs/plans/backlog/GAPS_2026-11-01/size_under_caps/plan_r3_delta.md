| Finding → resolution | Required change |
|---|---|
| Architect 1 → maker quantity sites | Cover `ORDER_QTY`, both own-rest deductions and `make_qty`; RED proves subtraction equals actual remaining resting quantity. |
| Architect 2 → cumulative position cap | Under the execution lock, aggregate earlier open fills plus working/in-flight commitments; refuse two individually affordable orders whose combined cost exceeds the position cap. |
| Architect 3 → complete cap-read citation | Replace r2’s two-cap-only assertion with review-reported `operator_controls.py:540–541`; verify the entire read-before-apply block before implementation. |
| Architect 4 → maker replay assumptions | Include `strategy.py:159` design/replay assumptions in prospective PREREG and pin changes; preserve historical registrations. |
| Architect LOW → authority, latch, rounding | Supersede operator-owned q; persist intended quantity before dispatch; partial fills never reopen the trial; native quantity conversion never rounds upward. |
| Prediction-market 1 → final-q economics | Specify authoritative `fee_total`; recompute average price and exact break-even after every clamp/conversion; failure returns zero. |
| Prediction-market 2 → monthly headroom | Include MONTH in the three-cap minimum; subtract gross commitments without profit refunds; absent/invalid cap refuses. |
| Prediction-market 3 → bankroll/accessor | `B_eff = ledger_B` exclusively through the fail-closed accessor; report/balance freshness ≤24 h; typed refusal otherwise. |
| Prediction-market 4 → executable depth | Exclude actual own rests, orient YES/NO correctly and walk external levels; use final-size average fill price. |
| Prediction-market 5 → explicit prohibition | no Kelly, no fractional-Kelly, no proposed q. |
| Prediction-market 6 → purity/money | Immutable explicit inputs, deterministic fee callable, no I/O; Decimal money and quantity throughout. |
| Prediction-market LOW → lifecycle/recheck | Partial fills consume remaining headroom; fresh-book authorization repeats economics; UTC calendar month defines rollover. |

# SIZE-UNDER-CAPS — r3 delta
Status: DRAFT; trading-bot-architect, prediction-market-reviewer and security-reviewer approval pending.
SUPERSEDES r2 ENTIRELY; overrides conflicting r1/review-status clauses. The table covers every numbered finding and both LOW paragraphs in [the review](/tmp/claude-1000/-home-jon-breezy/83eea2b1-e18b-40bb-8838-7106bb5f661f/scratchpad/rev_size_r2.md:1).

## 1 Objective + ROI mechanism
GOAL STATE: a qualified family calls pure `size()` directly and carries its computed quantity through native order construction and atomic execution authorization.
WALK: qualified frozen family → accessor-gated capital → external depth/fees → sizing → durable intent/reservation → authorized submission.
Additional positive-net-edge fills can increase portfolio dollars within caps; engineering PASS alone proves neither positive ROI nor family eligibility. Reports provide observability, never an execution handoff.

## 2 Preconditions/dependencies
The [2026-11-02 ruling](/home/jon/breezy/docs/core/PROGRESS.md:58) controls: only DAY/POSITION/MONTH cap values are operator decisions; all other bot decisions require no further operator selection.
S0: architect + prediction-market-reviewer land a dated architecture amendment before implementation, reconciling §6.2.1/6.3/6.4 with this ruling and the Kelly ban.
Remove Kelly-derived boundary tables/fallbacks, D2 approval and inherited additional monetary ceilings; preserve correlation/statistical safeguards without inventing another spend cap.
Require ROI-LEDGER A3/A5 and OPERATOR-CONTROLS-MONTHLY-CAP #11 before positive execution; require each consumer’s prospective frozen PREREG and applicable GAP evidence.
Reconcile #11’s documented pre-fee unit with this contract’s fee-inclusive sizing/authorization commitments before implementation; unresolved unit disagreement blocks delivery ([monthly plan:6](/home/jon/breezy/docs/plans/backlog/GAPS_2026-11-01/operator_controls_monthly_cap/plan_r0.md:6)).
Arming/retirement belongs to AUTO-PROMOTE-RETIRE; Kalshi additionally requires GAP-6 GO and its adapter. This item changes no live enablement.

## 3 Scope and source targets
Proposed: pure `src/breezy/domain/sizing.py`, accessor composition, focused tests, family quantity/latch wiring, cumulative position authorization and observability serialization without a new persistence unit.
Review-reported FQ targets, UNVERIFIED: [decision.py:73,168](/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/decision.py:73), [persistent_latch.py:64–67](/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/persistent_latch.py:64), [trial_day_latch.py:1009](/home/jon/breezy/src/breezy/strategy/current_rung_hold/trial_day_latch.py:1009).
Review-reported maker targets, UNVERIFIED: [strategy.py:159–160,524,531,681](/home/jon/breezy/src/breezy/strategy/no_ladder_maker/strategy.py:159): replay assumption, `ORDER_QTY`, both `own_excluded` calls and `make_qty`.
Review-reported authorization targets, UNVERIFIED: [operator_controls.py:540–541,543,561–569](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:540); verify both reads and cumulative accounting under `self._lock`.
Before coding, use CodeGraph to verify these targets, affected callers/pins and native extension alternatives; establish the enforceable accessor-only import boundary.

## 4 Steps and full pure contract
S0 owners: architect + prediction-market-reviewer; output the reconciled amendment and frozen contract. Builder then delivers RED-first sizing/accessor integration, family consumption, lifecycle accounting and reviewable evidence, sequentially.
`size(p_lb, bought_leg, book, own_rests, limit, B_eff, headrooms, instrument, policy, fee_total) -> SizeResult(q: Decimal, refusal: Refusal | None)`.
All inputs are immutable snapshots; `policy` carries frozen bot-derived slippage/freshness rules, not operator allocations. No clock/environment/filesystem reads, mutable globals or provider imports inside `size()`.
Validate finite Decimals, `0 <= p_lb < 1`, valid bought-leg prices, positive increment/minimum and complete input provenance; `p_lb >= 1` raises. Missing operational evidence returns zero with a typed refusal.
Caps come only from gitignored operator.env through validated composition; agents/code never assign, default, infer, raise or propose their values. Invalid/missing any cap returns zero.
`ledger_B = view.available_capital`; `B_eff = ledger_B`, obtained ONLY through `read_roi_for_decision(path, now)`; no report-scalar fallback, reconstructed equity or additional P&L credit.
Require accessor A3/A5 gates: acceptable schema, ROI/D8 OK, zero unverified fees/gated labels, required consumer fields, aware `generated_at` age in [0,24 h], and balance `observed_at` age in [0,24 h].
Accessor `None`, absent/stale capital or unknown accounting basis → typed zero refusal. Label balance evidence “lagged ≤1 day”; reconcile post-observation changes/reservations exactly once.
`H_day=max(0,day_cap-gross_day_commitments)`; `H_month=max(0,month_cap-gross_month_commitments)`; periods are UTC calendar day/month.
`H_position=max(0,position_cap-open_position_cost_and_fees-working_and_inflight_reservations)`; aggregate by stable position identity across orders, families and restarts, never per submission.
Gross period commitments include entry fills plus unresolved reservations exactly once; profits, sales and settlement never refund gross spending. Release only proven unused reservations; carry unresolved exposure across boundaries.
`H_B` is spendable `B_eff` after changes/commitments not already reflected in that balance; do not subtract the same open cost/reservation twice. Unknown exposure/basis refuses.
Transform Depth10 into bought-leg prices, subtract actual remaining own rests at every affected level, then walk external executable levels at/better than the limit; no QuoteTick substitution or extrapolation.
Let `D_ext` be external capacity; derive validated `c_guard>0` bounding fee-inclusive, monetarily rounded unit cost for every admissible quantity.
`q0=floor_increment(min(D_ext,H_day/c_guard,H_position/c_guard,H_month/c_guard,H_B/c_guard))`; below instrument minimum → zero; never round up.
Walk again at `q0`: `p_bar=sum(q_i*price_i)/q0`. Maker conditional fills use their posted limit as average price; external depth never establishes a maker fill guarantee.
`fee_total(q,fill_plan,liquidity)` returns authoritative nonnegative total USD fees using verified market θ and venue rounding/charging granularity; maker zero, no rebate credit or unrounded estimate substitution.
Do not apply a nonlinear fee formula to average price as though it reproduced multi-price or split-fill charges; prove conservative reservation coverage for partial fills, otherwise refuse.
At FINAL q recompute fill plan, average price and fees; require `p_lb > p_bar + fee_total(q,...)/q + slippage_margin`. Equality or failure → zero, without searching smaller quantities.
Recheck exact rounded premium plus fees against DAY/POSITION/MONTH and `H_B`, and q against depth/increment/minimum; native `make_qty` must preserve or reduce q, followed by the same final checks.
Immediately before submission, refresh cap reads, book, commitments and accessor eligibility; under the execution lock re-size/retest and atomically reserve before dispatch. Changed evidence may reduce/refuse, never bypass checks.
Persist intended q in durable IN_FLIGHT before sending; partial fills consume one trial and convert reservations to booked cost once. Freeze terminal-no-fill, ambiguity, restart, duplicate-event and cancel/replace semantics.
Maker exclusion uses actual remaining quantities, including partials and pending replacements; prospective FQ/maker consumption removes fixed-q assumptions while historical qty-1 registrations remain unchanged.
no Kelly, no fractional-Kelly, no proposed q. The bot computes execution quantity; no numeric quantity recommendation or operator quantity approval.

## 5 Frozen acceptance / PASS–KILL
PASS requires production-default family → real `size()` → native quantity >1 in an isolated fixture, plus zero-size refusal before dispatch and complete cumulative-cap/lifecycle proof.
Keep finite nonnegative output, all three monetary bounds, capital/depth bounds, increment/minimum checks, inclusive economic refusal and parsed-instrument minimum/increment CONTRACT.
S0 explicitly retires the Kelly-bound property and revises monotonicity claims: rounded-fee/final-average-price refusals do not imply globally monotone accepted quantities.
KILL delivery for undercounted commitments, raw financial fallback, unsupported fee coverage, missing evidence or any required weakening of a barrier; economic PASS/KILL remains the family’s frozen rule.

## 6 Tests RED-first + gates
RED cases: both individually affordable orders exceeding cumulative position capacity; concurrency/retry exhaustion; absent/invalid MONTH; UTC rollover/restart/carryover; own-rest subtraction equals remaining resting quantity.
Cover final-clamped-q fee-rounding/equality failures, multi-level YES/NO average prices, maker-zero/rebate rejection, stale/missing accessor gates, native round-up rejection and fresh-book loss of edge.
Cover intended-q IN_FLIGHT, partial-fill/duplicate/AMBIGUOUS/terminal recovery, unchanged statistical unit, maker replay self-order echo and forbidden raw-provider imports through actual consumer paths.
Use isolated existing harness fixtures; record RED → GREEN → clamp/import/latch mutation fails → restored GREEN; run focused tests, `.venv/bin/lint-imports`, then `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/size-under-caps`; read EXIT.

## 7 Pins/isolation/risks
Recompute affected producer closures and prospective PREREG/policy/quantity-schema pins, including maker replay/design assumptions; L-12 widening requires its separate reviewed re-pin, never relaxed equality.
Nautilus immutable; `allow_short=False`; preserve permit/latch/safety/settlement/contract/pin/NO-SEND barriers, holdout clauses 1–4, frozen PREREG and ONE look; existing harness only unless an exception is named exactly.
L-75 writer-produced evidence only; no credentials/order IDs in git, no `iem_cli_fetch.fetch`, new ledger/service or live-state changes; no assumed daily capital turnover or cross-process/venue cap guarantee.

## 8 Operator decisions
Exactly three values: maximum USD per DAY, per POSITION and per MONTH, read only from gitignored operator.env. Everything else belongs to the bot and engineering review within those caps.

## 9 Unverified
CodeGraph unavailable: every §3 code locator is review-reported and unverified; implementation must await the required `mcp__codegraph__codegraph_explore(projectPath=/home/jon/breezy)` checks.
Sequential Thinking unavailable; native-reuse verdict, source call paths, fee granularity, affected pins, dependency delivery and family eligibility remain unverified.
No implementation, tests, gates or live checks performed; no files edited, created or staged; final `git status --short` remained clean.
